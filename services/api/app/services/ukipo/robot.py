"""Playwright robot for UK IPO trade mark filing.

Drives https://trademarks.ipo.gov.uk/ipo-apply from the start screen all
the way to the declaration page, then STOPS before the
"Pay for and submit application" button. Payment happens off-platform
(on-chain) — the caller is responsible for that.

This module is intentionally DB-unaware: it accepts a ``RobotInput``
dataclass and returns a ``RobotResult``. The caller (service.py) is
responsible for persistence and for translating result → submission row.

Playwright is imported lazily inside ``run_submission`` so unit tests
(which never run the real browser) don't need the browser binaries.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from playwright.async_api import Locator, Page

# Async callback the runner invokes once per step *before* the step runs.
# The service uses it to persist `current_step` so the frontend's polling
# UI can show "where the robot is right now" without coupling robot to DB.
ProgressCallback = Callable[[str], Awaitable[None]]

from app.services.ukipo.models import UKIPOMarkType, UKIPOOwnerEntityType

logger = logging.getLogger(__name__)


# Local UK normalisation set — duplicated in schemas.py and service.py
# on purpose so each layer can validate without coupling.
_UK_COUNTRY_VALUES = frozenset({
    "united kingdom",
    "uk",
    "gb",
    "great britain",
    "england",
    "scotland",
    "wales",
    "northern ireland",
})


def _is_uk(country: str | None) -> bool:
    if not country:
        return False
    return country.strip().lower() in _UK_COUNTRY_VALUES


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NiceClassInput:
    class_number: int
    description: str


@dataclass
class OwnerData:
    company_name: str
    country: str
    address_line1: str
    address_line2: str | None
    city: str
    postcode: str | None
    email: str | None
    phone: str | None
    entity_type: UKIPOOwnerEntityType
    company_registration_number: str | None

    def __post_init__(self) -> None:
        if _is_uk(self.country) and not (self.postcode and self.postcode.strip()):
            raise ValueError(
                "postcode is required when owner.country is in the United Kingdom"
            )


@dataclass
class RepresentativeData:
    entity_type: str
    name: str
    email: str
    phone: str
    address_line1: str
    address_line2: str | None
    city: str
    postcode: str
    country: str


@dataclass
class RobotInput:
    owner: OwnerData
    representative: RepresentativeData
    declarant_name: str
    mark_type: UKIPOMarkType
    mark_text: str | None
    mark_image_path: str | None
    nice_classes: list[NiceClassInput]
    submission_id: str

    def __post_init__(self) -> None:
        if not self.nice_classes:
            raise ValueError("at least one Nice class is required")
        if self.mark_type in (UKIPOMarkType.word, UKIPOMarkType.combined):
            if not self.mark_text or not self.mark_text.strip():
                raise ValueError(
                    f"mark_text is required for mark_type={self.mark_type.value}"
                )
        if self.mark_type in (
            UKIPOMarkType.figurative,
            UKIPOMarkType.combined,
            UKIPOMarkType.unusual,
        ):
            if not self.mark_image_path or not self.mark_image_path.strip():
                raise ValueError(
                    f"mark_image_path is required for mark_type={self.mark_type.value}"
                )


@dataclass
class RobotResult:
    success: bool
    current_step: str
    ipo_application_url: str | None = None
    screenshot_path: str | None = None
    error_step: str | None = None
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UKIPO_FORM_URL = "https://trademarks.ipo.gov.uk/ipo-apply"

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-GB','en','en-US'] });
window.chrome = window.chrome || { runtime: {} };
"""

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Steps in execution order — used for telemetry and resume logic.
STEPS = (
    "open_form",
    "choose_representative_role",
    "fill_representative_details",
    "fill_owner_details",
    "choose_mark_type",
    "single_trade_mark",
    "select_class_manually",
    "enter_nice_classes",
    "confirm_bottom_option",
    "answer_no_questions",
    "choose_standard_mark",
    "choose_examination_type",
    "declaration",
)

OWNER_ENTITY_LABEL_TO_FIELD: dict[UKIPOOwnerEntityType, tuple[str, ...]] = {
    UKIPOOwnerEntityType.registered_company_or_llp: (
        "ownerEntityCompanyName",
    ),
    UKIPOOwnerEntityType.individuals: (
        "ownerEntityName",
    ),
    UKIPOOwnerEntityType.partnership: (
        "ownerEntityPartnershipName",
    ),
    UKIPOOwnerEntityType.trust: (
        "ownerEntityTrustName",
    ),
    UKIPOOwnerEntityType.other: (
        "ownerEntityName",
        "ownerEntityCompanyName",
    ),
}


# ---------------------------------------------------------------------------
# Helpers (page primitives)
# ---------------------------------------------------------------------------


async def _wait_cloudflare(page: "Page", timeout_seconds: int = 45) -> None:
    """Block until any Cloudflare challenge / human-check page clears."""
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        try:
            title = (await page.title()).lower()
            body = (await page.locator("body").inner_text(timeout=1500)).lower()
        except Exception:
            await asyncio.sleep(1)
            continue
        markers = (
            "just a moment",
            "security check",
            "checking your browser",
            "verify you are human",
        )
        if not any(m in title or m in body for m in markers):
            return
        await asyncio.sleep(1)
    logger.warning("ukipo: cloudflare challenge did not clear in %ss", timeout_seconds)


async def _dismiss_cookies(page: "Page") -> None:
    """Click whichever cookie-consent button is visible.

    The banner sometimes re-appears after a navigation (HTML cookies
    not set yet because of strict-same-site rules), so this is safe to
    call repeatedly — it no-ops when no button is visible.
    """
    candidates = [
        "Accept all",
        "Accept additional cookies",
        "Reject additional cookies",
    ]
    for label in candidates:
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if await btn.count():
                visible = await _first_visible(btn)
                if visible is not None:
                    await visible.click()
                    break
        except Exception:
            continue
    try:
        hide = page.get_by_role("button", name=re.compile(r"Hide this message", re.I))
        if await hide.count():
            visible = await _first_visible(hide)
            if visible is not None:
                await visible.click()
    except Exception:
        pass


async def _check_validation_errors(page: "Page", step: str) -> None:
    """Raise if the IPO error summary is on screen after a Continue."""
    try:
        body = (await page.locator("body").inner_text(timeout=1500)).lower()
    except Exception:
        return
    if "there was a problem submitting the form" not in body:
        return
    msgs: list[str] = []
    for sel in (".govuk-error-summary li", ".govuk-error-message"):
        try:
            count = await page.locator(sel).count()
            for i in range(count):
                txt = (await page.locator(sel).nth(i).inner_text()).strip()
                if txt:
                    msgs.append(txt)
        except Exception:
            continue
    raise RuntimeError(
        f"UK IPO validation error at step={step}: " + "; ".join(msgs[:10])
    )


async def _first_visible(locator: "Locator") -> "Locator | None":
    """Return the first visible match of a locator, or None if none visible."""
    count = await locator.count()
    for i in range(count):
        loc = locator.nth(i)
        try:
            if await loc.is_visible():
                return loc
        except Exception:
            continue
    return None


async def _dump_visible_form_inputs(page: "Page") -> str:
    """Return a compact description of every visible input/select/textarea.

    Used in error paths so when the spec's hand-coded selectors no
    longer match IPO's live HTML we surface the actual ``name``,
    ``id`` and visible label of each control. The operator forwards
    this to the dev who can patch the selector list without having to
    re-run the form by hand.
    """
    try:
        items = await page.evaluate(
            """() => {
                const rows = [];
                const els = document.querySelectorAll(
                    'input, select, textarea'
                );
                for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    if (el.type === 'hidden') continue;
                    const lbl = el.labels && el.labels[0]
                        ? el.labels[0].textContent.trim().slice(0, 60)
                        : null;
                    rows.push({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || null,
                        name: el.name || null,
                        id: el.id || null,
                        label: lbl,
                    });
                }
                return rows;
            }"""
        )
    except Exception as exc:
        return f"<dump failed: {exc}>"
    if not items:
        return "<no visible form controls>"
    parts = []
    for r in items[:40]:
        parts.append(
            f"{r.get('tag')}({r.get('type')})"
            f" name={r.get('name')!r}"
            f" id={r.get('id')!r}"
            f" label={r.get('label')!r}"
        )
    return "; ".join(parts)


async def _wait_form_ready(
    page: "Page",
    *,
    selectors: tuple[str, ...] = (),
    label: str | None = None,
    timeout_ms: int = 8000,
) -> None:
    """Wait until *something* identifying the new form is in DOM.

    IPO's form-section reveal is JS-driven: the "Add ... details" link
    triggers a delayed mount, and during that window neither labels nor
    inputs are queryable. We poll for any of the given CSS selectors or
    a label match — whichever appears first wins. Best-effort: if
    nothing surfaces within ``timeout_ms`` we just return and let the
    caller's specific lookups fail with a clearer message.
    """
    deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000)
    while asyncio.get_event_loop().time() < deadline:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if await loc.count() and await loc.first.is_visible():
                    return
            except Exception:
                continue
        if label is not None:
            try:
                loc = page.get_by_label(re.compile(label, re.I), exact=False)
                if await loc.count() and await loc.first.is_visible():
                    return
            except Exception:
                pass
        await asyncio.sleep(0.2)


async def _real_type(page: "Page", el: "Locator", value: str) -> None:
    """Click → select-all → delete → type with a per-key delay.

    Plain ``fill()`` sometimes does not propagate to IPO's internal
    framework state; real keyboard typing does. After typing we read the
    value back to make sure something stuck.
    """
    await el.click()
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Delete")
    await el.type(value, delay=30)
    actual = await el.input_value()
    if actual.strip() != value.strip():
        raise RuntimeError(
            f"input value mismatch: expected={value!r} actual={actual!r}"
        )


async def _select_with_change(page: "Page", el: "Locator", value: str) -> None:
    """select_option with a manual change-event bounce + tolerant matching.

    IPO's <select> handlers sometimes don't fire on a single
    ``select_option`` call. We bounce to a different option first, then
    settle on the target. Matching tries (in order):

    1. exact value=
    2. exact label=
    3. case-insensitive label match
    4. label whose first significant token matches (e.g. "Anguilla
       (United Kingdom)" -> the IPO option "Anguilla")
    5. label that *contains* the requested value as a substring

    On total mismatch we raise with the dropdown's actual options so the
    operator can pick one that exists.
    """
    try:
        options: list[dict[str, str]] = await el.evaluate(
            "el => Array.from(el.options).map(o => "
            "({value: o.value, label: o.textContent.trim()}))"
        )
    except Exception:
        options = []

    bounce_value = next(
        (o["value"] for o in options if o["value"] and o["value"] != value),
        None,
    )
    if bounce_value:
        try:
            await el.select_option(bounce_value)
        except Exception:
            pass

    target = _resolve_select_option(options, value)
    if target is None:
        sample = ", ".join(
            o["label"] for o in options if o.get("label")
        )[:600]
        raise RuntimeError(
            f"select has no option matching {value!r}. "
            f"Available options: {sample}"
        )

    if target.get("value"):
        await el.select_option(target["value"])
    else:
        await el.select_option(label=target["label"])

    await el.evaluate(
        """el => {
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        }"""
    )


def _resolve_select_option(
    options: list[dict[str, str]], value: str
) -> dict[str, str] | None:
    """Return the best-matching option dict or None.

    The IPO Country dropdown lists countries with their official names;
    user input may carry parenthetical context like "Anguilla (United
    Kingdom)" or use mixed case. We progressively relax the match.
    """
    if not options:
        return None
    target = value.strip()
    target_lower = target.lower()
    target_main = target.split("(")[0].strip()
    target_main_lower = target_main.lower()

    for o in options:
        if o.get("value") == target or o.get("label") == target:
            return o
    for o in options:
        if (o.get("label") or "").strip().lower() == target_lower:
            return o
    for o in options:
        if (o.get("label") or "").strip().lower() == target_main_lower:
            return o
    for o in options:
        label = (o.get("label") or "").strip().lower()
        if not label:
            continue
        if (
            label.startswith(target_main_lower)
            or target_main_lower.startswith(label)
        ):
            return o
    for o in options:
        label = (o.get("label") or "").strip().lower()
        if target_main_lower and target_main_lower in label:
            return o
    return None


async def _ladder_check(page: "Page", el: "Locator") -> None:
    """Try multiple strategies to tick a checkbox the form actually accepts."""
    try:
        await el.check()
        if await el.is_checked():
            return
    except Exception:
        pass
    try:
        await el.check(force=True)
        if await el.is_checked():
            return
    except Exception:
        pass
    try:
        label = el.locator("xpath=ancestor::label[1]")
        if await label.count():
            await label.first.click()
            if await el.is_checked():
                return
    except Exception:
        pass
    await el.evaluate(
        """el => { el.checked = true;
                   el.dispatchEvent(new Event('change', {bubbles:true})); }"""
    )


async def _fill_named(
    page: "Page",
    name: str,
    value: str,
    *,
    required: bool = True,
) -> bool:
    """Fill an input picked by ``name`` attribute. Returns True if filled."""
    locator = page.locator(f"input[name='{name}'], textarea[name='{name}']")
    el = await _first_visible(locator)
    if el is None:
        if required:
            raise RuntimeError(f"input name={name!r} is not visible on page")
        return False
    await _real_type(page, el, value)
    return True


async def _fill_by_label_or_name(
    page: "Page",
    *,
    labels: tuple[str, ...],
    names: tuple[str, ...],
    value: str,
) -> None:
    for name in names:
        locator = page.locator(f"input[name='{name}'], textarea[name='{name}']")
        el = await _first_visible(locator)
        if el is not None:
            await _real_type(page, el, value)
            return
    for label in labels:
        try:
            locator = page.get_by_label(re.compile(label, re.I), exact=False)
            el = await _first_visible(locator)
            if el is not None:
                await _real_type(page, el, value)
                return
        except Exception:
            continue
    raise RuntimeError(
        f"could not find input for labels={labels} or names={names}"
    )


async def _click_continue(page: "Page") -> None:
    btn = page.get_by_role("button", name=re.compile(r"^continue\s*$", re.I))
    if await btn.count() == 0:
        btn = page.locator("button", has_text=re.compile(r"^continue", re.I))
    visible = await _first_visible(btn)
    if visible is None:
        raise RuntimeError("Continue button not visible")
    await visible.click()
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass


async def _screenshot(page: "Page", path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        await page.screenshot(path=path, full_page=True)
    except Exception as exc:
        logger.warning("ukipo: screenshot failed at %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


async def _step_open_form(page: "Page") -> None:
    await page.goto(UKIPO_FORM_URL, wait_until="domcontentloaded")
    await _wait_cloudflare(page)
    await _dismiss_cookies(page)
    for label in (r"Start now", r"Begin application"):
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I))
            if await btn.count() == 0:
                btn = page.get_by_role("link", name=re.compile(label, re.I))
            visible = await _first_visible(btn)
            if visible is not None:
                await visible.click()
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                return
        except Exception:
            continue


async def _step_choose_representative_role(page: "Page") -> None:
    radio = page.get_by_label(re.compile(r"attorney,?\s+solicitor", re.I))
    visible = await _first_visible(radio)
    if visible is None:
        raise RuntimeError("representative-role radio not visible")
    await visible.check()
    await _click_continue(page)
    await _check_validation_errors(page, "choose_representative_role")


async def _step_fill_representative_details(
    page: "Page", rep: RepresentativeData
) -> None:
    add_link = page.get_by_role(
        "link", name=re.compile(r"Add representative details", re.I)
    )
    if await add_link.count() == 0:
        add_link = page.get_by_role(
            "button", name=re.compile(r"Add representative details", re.I)
        )
    visible = await _first_visible(add_link)
    if visible is not None:
        await visible.click()
    # The cookie banner sometimes survives the initial dismissal — try
    # again now that the form view is mounted, otherwise it can shadow
    # the country dropdown's hit area on some viewports.
    await _dismiss_cookies(page)

    # Wait for the rep details form to actually mount in DOM.
    # Without this we sometimes start typing before any input has
    # rendered (the link click triggers a JS-side reveal), and the
    # first Country/select_with_change re-render can knock fields out
    # of DOM mid-operation.
    await _wait_form_ready(
        page,
        selectors=(
            "input[name='representativeName']",
            "input[name='repName']",
            "input[id*='representative' i]",
        ),
        label=r"Full name",
    )

    await _select_field_by_label(
        page,
        r"Representative type",
        rep.entity_type,
        names=("representativeEntityType", "repEntityType"),
    )
    await asyncio.sleep(0.4)
    await _fill_by_label_or_name(
        page,
        labels=(r"Full name", r"Your name"),
        names=("representativeName", "repName", "representativeFullName"),
        value=rep.name,
    )
    await asyncio.sleep(0.4)
    await _select_field_by_label(
        page,
        r"^Country",
        rep.country,
        names=(
            "representativeEntityCountry",
            "repEntityCountry",
            "representativeCountry",
        ),
    )
    await asyncio.sleep(0.3)
    if rep.postcode:
        await _fill_by_label_or_name(
            page,
            labels=(r"Postcode",),
            names=("representativeEntityGBPostcode", "representativePostcode"),
            value=rep.postcode,
        )
    await _fill_by_label_or_name(
        page,
        labels=(r"^Address",),
        names=("representativeEntityAddressLine1", "representativeAddressLine1"),
        value=rep.address_line1,
    )
    if rep.address_line2:
        await _fill_named(
            page, "representativeEntityAddressLine2", rep.address_line2, required=False
        )
    await _fill_by_label_or_name(
        page,
        labels=(r"Town or city",),
        names=("representativeEntityTown", "representativeTown"),
        value=rep.city,
    )
    await _fill_by_label_or_name(
        page,
        labels=(r"Telephone number",),
        names=("representativeEntityTelNumber", "representativePhone"),
        value=rep.phone,
    )
    await _fill_by_label_or_name(
        page,
        labels=(r"^Email address",),
        names=("representativeEntityEmail", "representativeEmail"),
        value=rep.email,
    )
    await _fill_by_label_or_name(
        page,
        labels=(r"Confirm email address",),
        names=("representativeEntityConfirmEmail", "representativeConfirmEmail"),
        value=rep.email,
    )

    consent = page.get_by_label(
        re.compile(r"I understand the IPO will use my email address", re.I)
    )
    visible = await _first_visible(consent)
    if visible is not None:
        await _ladder_check(page, visible)

    await _click_continue(page)
    await _check_validation_errors(page, "fill_representative_details")


async def _select_field_by_label(
    page: "Page",
    label: str,
    value: str,
    *,
    names: tuple[str, ...] = (),
) -> None:
    """Resolve a ``<select>`` by name first, label second.

    IPO sometimes wraps labels in heading/legend elements that
    ``get_by_label`` doesn't associate with the input. The form's name
    attributes are stable across renders, so when we know them (e.g.
    ``representativeEntityCountry``) we match those first and only fall
    back to label matching if no visible select is found.
    """
    for name in names:
        loc = page.locator(f"select[name='{name}']")
        el = await _first_visible(loc)
        if el is not None:
            await _select_with_change(page, el, value)
            return
    locator = page.get_by_label(re.compile(label, re.I), exact=False)
    el = await _first_visible(locator)
    if el is None:
        raise RuntimeError(
            f"select field for label={label!r} (names={names}) not visible"
        )
    await _select_with_change(page, el, value)


async def _step_fill_owner_details(page: "Page", owner: OwnerData) -> None:
    # The page has both a representative and an owner block; the owner
    # link is the *last* of the duplicated "Add ... details" links.
    add_link = page.get_by_role(
        "link", name=re.compile(r"Add name and address details", re.I)
    )
    if await add_link.count() == 0:
        add_link = page.get_by_role(
            "button", name=re.compile(r"Add name and address details", re.I)
        )
    if await add_link.count():
        await add_link.last.click()
    await _dismiss_cookies(page)
    await _wait_form_ready(
        page,
        selectors=(
            "select[name='ownerEntityType']",
            "select[name*='owner' i]",
        ),
        label=r"Owner type",
    )

    # Pick owner type FIRST — this rerenders the visible inputs.
    await _select_field_by_label(
        page,
        r"Owner type",
        owner.entity_type.value,
        names=("ownerEntityType",),
    )
    await asyncio.sleep(0.5)

    # On the redesigned form the owner Country select sometimes drives
    # which company-name input renders, so set it BEFORE searching for
    # the name field. The "Country of incorporation" select still gets
    # set further down for Reg Co cases.
    try:
        await _select_with_change(
            page,
            page.locator("select[name='ownerEntityCountry']"),
            owner.country,
        )
        await asyncio.sleep(0.4)
    except Exception:
        pass

    # Company name field name varies by entity type. Try the documented
    # names first, then a broader scan, then fall back to dumping what
    # *is* visible so the operator can see what IPO renders today.
    name_fields = OWNER_ENTITY_LABEL_TO_FIELD[owner.entity_type]
    extra_name_patterns = (
        "ownerCompanyName",
        "ownerName",
        "applicantCompanyName",
        "applicantName",
        "companyName",
        "registeredCompanyName",
    )
    filled = False
    for fname in (*name_fields, *extra_name_patterns):
        try:
            if await _fill_named(page, fname, owner.company_name, required=False):
                filled = True
                break
        except Exception:
            continue
    if not filled:
        # Last-ditch: any visible text input whose name contains "name"
        # (case-insensitive) that isn't already an address/town/email/phone.
        loc = page.locator(
            "input[type='text'][name*='ame' i]:not([name*='Address' i])"
            ":not([name*='Town' i]):not([name*='Email' i])"
            ":not([name*='Phone' i]):not([name*='Tel' i])"
        )
        el = await _first_visible(loc)
        if el is not None:
            await _real_type(page, el, owner.company_name)
            filled = True
    if not filled:
        snapshot = await _dump_visible_form_inputs(page)
        raise RuntimeError(
            f"could not find visible company-name input for entity_type="
            f"{owner.entity_type.value}. Visible inputs on page: {snapshot}"
        )

    if owner.entity_type == UKIPOOwnerEntityType.registered_company_or_llp:
        await _select_with_change(
            page,
            page.locator("select[name='ownerEntityIncCountry']"),
            owner.country,
        )
        if owner.company_registration_number:
            target_field = (
                "ownerEntityCompReg" if _is_uk(owner.country) else "ownerEntityCompRegNotUK"
            )
            await _fill_named(
                page,
                target_field,
                owner.company_registration_number,
                required=_is_uk(owner.country),
            )

    await _select_with_change(
        page,
        page.locator("select[name='ownerEntityCountry']"),
        owner.country,
    )

    # Address block FIRST so the postcode-lookup blur doesn't overwrite.
    await _fill_named(page, "ownerEntityAddressLine1", owner.address_line1)
    if owner.address_line2:
        await _fill_named(
            page, "ownerEntityAddressLine2", owner.address_line2, required=False
        )
    await _fill_named(page, "ownerEntityTown", owner.city)
    if owner.phone:
        await _fill_named(page, "ownerEntityTelNumber", owner.phone, required=False)
    if owner.email:
        await _fill_named(page, "ownerEntityEmail", owner.email, required=False)
        await _fill_named(
            page, "ownerEntityConfirmEmail", owner.email, required=False
        )

    # Postcode last — UK lookup may auto-populate other fields, so we
    # re-apply user values right after.
    if _is_uk(owner.country):
        if not owner.postcode:
            raise RuntimeError("UK owner without postcode reached robot — refusing")
        await _fill_named(page, "ownerEntityGBPostcode", owner.postcode)
        try:
            find_btn = page.get_by_role(
                "button", name=re.compile(r"Find UK address", re.I)
            )
            visible = await _first_visible(find_btn)
            if visible is not None:
                await visible.click()
                await asyncio.sleep(3)
                lookup_select = page.locator("select[name*='addressLookup']")
                if await lookup_select.count() and await lookup_select.first.is_visible():
                    options: list[str] = await lookup_select.first.evaluate(
                        "el => Array.from(el.options).map(o => o.value).filter(Boolean)"
                    )
                    if options:
                        await _select_with_change(
                            page, lookup_select.first, options[0]
                        )
        except Exception as exc:
            logger.warning("ukipo: address lookup failed: %s", exc)
        # Re-apply user values so Royal Mail data doesn't shadow them.
        await _fill_named(page, "ownerEntityAddressLine1", owner.address_line1)
        await _fill_named(page, "ownerEntityTown", owner.city)
    elif owner.postcode:
        await _fill_named(
            page, "ownerEntityROWPostcode", owner.postcode, required=False
        )

    for cb_name in (
        "ownerEntityEmailUse",
        "ownerEntityApplicantAcknowledgement",
        "ownerEntityApplicantConfirmation",
    ):
        cb = page.locator(f"input[name='{cb_name}'][type='checkbox']")
        visible = await _first_visible(cb)
        if visible is None:
            raise RuntimeError(f"required owner checkbox {cb_name} not visible")
        await _ladder_check(page, visible)

    await _click_continue(page)
    await _check_validation_errors(page, "fill_owner_details")


_MARK_TYPE_RADIO_PATTERNS: dict[UKIPOMarkType, str] = {
    UKIPOMarkType.word: r"only\s+words,?\s+letters\s+or\s+numbers",
    UKIPOMarkType.figurative: r"picture\s+without\s+words",
    UKIPOMarkType.combined: r"words,?\s+letters\s+or\s+numbers\s+in\s+a\s+particular\s+style",
    UKIPOMarkType.unusual: r"unusual\s+type\s+of\s+trade\s+mark",
}


async def _step_choose_mark_type(
    page: "Page",
    mark_type: UKIPOMarkType,
    mark_text: str | None,
    mark_image_path: str | None,
) -> None:
    # First the summary "Continue" to the radio page.
    await _click_continue(page)
    pattern = _MARK_TYPE_RADIO_PATTERNS[mark_type]
    radio = page.get_by_label(re.compile(pattern, re.I))
    visible = await _first_visible(radio)
    if visible is None:
        raise RuntimeError(f"mark-type radio for {mark_type.value} not visible")
    await visible.check()
    await _click_continue(page)

    if mark_type in (UKIPOMarkType.word, UKIPOMarkType.combined):
        if not mark_text:
            raise RuntimeError("mark_text required but missing")
        await _fill_by_label_or_name(
            page,
            labels=(r"Enter the words, letters or numbers contained in the trade mark",),
            names=("wordPhrase", "tradeMarkText", "wordMark", "markText"),
            value=mark_text,
        )

    if mark_type in (
        UKIPOMarkType.figurative,
        UKIPOMarkType.combined,
        UKIPOMarkType.unusual,
    ):
        if not mark_image_path:
            raise RuntimeError("mark_image_path required but missing")
        file_input = page.locator("input[type='file']")
        visible_file = await _first_visible(file_input)
        if visible_file is None:
            visible_file = file_input.first
        await visible_file.set_input_files(mark_image_path)

    await _click_continue(page)
    await _check_validation_errors(page, "choose_mark_type")


async def _step_single_trade_mark(page: "Page") -> None:
    radio = page.get_by_label(re.compile(r"^\s*Single trade mark", re.I))
    visible = await _first_visible(radio)
    if visible is None:
        raise RuntimeError("'Single trade mark' radio not visible")
    await visible.check()
    await _click_continue(page)
    # Info page → another Continue.
    await _click_continue(page)
    await _check_validation_errors(page, "single_trade_mark")


async def _step_select_class_manually(page: "Page") -> None:
    targets = (
        page.get_by_role(
            "link", name=re.compile(r"Select class and enter manually", re.I)
        ),
        page.get_by_role(
            "button", name=re.compile(r"Select class and enter manually", re.I)
        ),
        page.get_by_text(re.compile(r"Select class and enter manually", re.I)),
    )
    for locator in targets:
        if await locator.count() == 0:
            continue
        visible = await _first_visible(locator)
        if visible is not None:
            await visible.click()
            return
    raise RuntimeError("'Select class and enter manually' card not found")


async def _step_enter_nice_classes(
    page: "Page", classes: list[NiceClassInput]
) -> None:
    for idx, entry in enumerate(classes):
        if idx > 0:
            await _step_select_class_manually(page)
        select_loc = page.locator("select[name='goodsClass']")
        if await select_loc.count() == 0:
            select_loc = page.get_by_label(re.compile(r"Select a class", re.I))
        sel_visible = await _first_visible(select_loc)
        if sel_visible is None:
            raise RuntimeError("Nice class select not visible")
        await _select_with_change(page, sel_visible, str(entry.class_number))

        ta_loc = page.locator("textarea[name='goodsDescription']")
        if await ta_loc.count() == 0:
            ta_loc = page.get_by_label(
                re.compile(r"Add your goods and/or services", re.I)
            )
        ta_visible = await _first_visible(ta_loc)
        if ta_visible is None:
            raise RuntimeError("Nice class description textarea not visible")
        await _real_type(page, ta_visible, entry.description)
        await _click_continue(page)
        await _check_validation_errors(page, f"enter_nice_classes[{entry.class_number}]")

    # Final Continue out of the summary.
    await _click_continue(page)
    await _check_validation_errors(page, "enter_nice_classes")


async def _step_confirm_bottom_option(page: "Page") -> None:
    patterns = (
        r"bona\s+fide\s+intention\s+to\s+use",
        r"making\s+a\s+legal\s+declaration",
        r"trade\s+mark\s+is\s+being\s+used",
    )
    checked = False
    for pat in patterns:
        try:
            cb = page.get_by_label(re.compile(pat, re.I))
            visible = await _first_visible(cb)
            if visible is not None:
                await _ladder_check(page, visible)
                checked = True
                break
        except Exception:
            continue
    if not checked:
        cb = page.locator(
            "main input[type='checkbox']:not([name*='ot-']):not([role='switch'])"
        )
        visible = await _first_visible(cb)
        if visible is None:
            raise RuntimeError("bona-fide checkbox not visible")
        await _ladder_check(page, visible)
    await _click_continue(page)
    await _check_validation_errors(page, "confirm_bottom_option")


async def _step_answer_no_questions(page: "Page", count: int = 3) -> None:
    for i in range(count):
        radio = page.get_by_label(re.compile(r"^\s*No\s*$", re.I))
        visible = await _first_visible(radio)
        if visible is None:
            raise RuntimeError(f"'No' radio not visible on page {i + 1}")
        await visible.check()
        await _click_continue(page)
        await _check_validation_errors(page, f"answer_no_questions[{i}]")


async def _step_choose_standard_mark(page: "Page") -> None:
    radio = page.get_by_label(re.compile(r"^\s*Standard trade mark", re.I))
    visible = await _first_visible(radio)
    if visible is None:
        raise RuntimeError("'Standard trade mark' radio not visible")
    await visible.check()
    await _click_continue(page)
    await _check_validation_errors(page, "choose_standard_mark")


async def _step_choose_examination_type(page: "Page") -> None:
    radio = page.get_by_label(re.compile(r"^\s*Standard examination", re.I))
    visible = await _first_visible(radio)
    if visible is None:
        raise RuntimeError("'Standard examination' radio not visible")
    await visible.check()
    await _click_continue(page)
    # Optional preview page.
    try:
        await _click_continue(page)
    except Exception:
        pass
    await _check_validation_errors(page, "choose_examination_type")


async def _step_declaration(page: "Page", declarant_name: str) -> None:
    main_cbs = page.locator(
        "main input[type='checkbox']:not([name*='ot-']):not([role='switch'])"
    )
    count = await main_cbs.count()
    for i in range(count):
        cb = main_cbs.nth(i)
        try:
            if not await cb.is_visible():
                continue
        except Exception:
            continue
        await _ladder_check(page, cb)

    name_filled = False
    for name in ("declarantName", "declarant_name"):
        try:
            if await _fill_named(page, name, declarant_name, required=False):
                name_filled = True
                break
        except Exception:
            continue
    if not name_filled:
        for label in (r"^Declarant Name$", r"^Declarant name$", r"^Full name$"):
            try:
                locator = page.get_by_label(re.compile(label, re.I))
                el = await _first_visible(locator)
                if el is not None:
                    await _real_type(page, el, declarant_name)
                    name_filled = True
                    break
            except Exception:
                continue
    if not name_filled:
        raise RuntimeError("declarant name input not visible on declaration page")


# ---------------------------------------------------------------------------
# Public runner
# ---------------------------------------------------------------------------


async def run_submission(
    inp: RobotInput,
    *,
    headless: bool = True,
    screenshot_dir: str | None = None,
    on_step_start: ProgressCallback | None = None,
) -> RobotResult:
    """Drive the UK IPO form end-to-end up to (but not past) the pay button.

    Returns a ``RobotResult`` describing where the robot landed. The
    result is the only signal the caller has — never raises on form
    failures (those are turned into ``success=False`` results).

    ``on_step_start`` is invoked with the step name *before* each step
    runs. It exists so the service layer can persist live progress for
    the polling UI without dragging a DB session into this module.
    Errors inside the callback are swallowed — robot must keep going.
    """
    from playwright.async_api import async_playwright

    base_dir = os.path.join(
        screenshot_dir or "/tmp/ukipo-screenshots", inp.submission_id
    )
    os.makedirs(base_dir, exist_ok=True)

    final_screenshot: str | None = None
    final_url: str | None = None
    current_step = "init"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=STEALTH_ARGS)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
        )
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        page = await context.new_page()

        try:
            for step in STEPS:
                current_step = step
                if on_step_start is not None:
                    try:
                        await on_step_start(step)
                    except Exception as exc:
                        logger.warning(
                            "ukipo: progress callback raised at step=%s: %s",
                            step,
                            exc,
                        )
                pre = os.path.join(base_dir, f"pre_{step}.png")
                await _screenshot(page, pre)

                if step == "open_form":
                    await _step_open_form(page)
                elif step == "choose_representative_role":
                    await _step_choose_representative_role(page)
                elif step == "fill_representative_details":
                    await _step_fill_representative_details(page, inp.representative)
                elif step == "fill_owner_details":
                    await _step_fill_owner_details(page, inp.owner)
                elif step == "choose_mark_type":
                    await _step_choose_mark_type(
                        page, inp.mark_type, inp.mark_text, inp.mark_image_path
                    )
                elif step == "single_trade_mark":
                    await _step_single_trade_mark(page)
                elif step == "select_class_manually":
                    await _step_select_class_manually(page)
                elif step == "enter_nice_classes":
                    await _step_enter_nice_classes(page, inp.nice_classes)
                elif step == "confirm_bottom_option":
                    await _step_confirm_bottom_option(page)
                elif step == "answer_no_questions":
                    await _step_answer_no_questions(page)
                elif step == "choose_standard_mark":
                    await _step_choose_standard_mark(page)
                elif step == "choose_examination_type":
                    await _step_choose_examination_type(page)
                elif step == "declaration":
                    await _step_declaration(page, inp.declarant_name)

                post = os.path.join(base_dir, f"post_{step}.png")
                await _screenshot(page, post)
                final_screenshot = post

            final_url = page.url
            return RobotResult(
                success=True,
                current_step="declaration",
                ipo_application_url=final_url,
                screenshot_path=final_screenshot,
            )
        except Exception as exc:
            err_path = os.path.join(base_dir, f"error_{current_step}.png")
            await _screenshot(page, err_path)
            try:
                final_url = page.url
            except Exception:
                final_url = None
            logger.exception("ukipo: robot failed at step=%s", current_step)
            return RobotResult(
                success=False,
                current_step=current_step,
                ipo_application_url=final_url,
                screenshot_path=err_path,
                error_step=current_step,
                error_message=str(exc),
            )
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
