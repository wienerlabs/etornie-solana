import httpx
from fastapi import HTTPException

from app.config import settings


class WhatsAppClient:
    """Async client for WhatsApp Business Cloud API."""

    def __init__(
        self,
        api_token: str,
        phone_number_id: str,
        api_version: str = "v22.0",
    ) -> None:
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{api_version}/{phone_number_id}"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        self._http = httpx.AsyncClient(timeout=30.0)

    async def _handle_response(self, response: httpx.Response) -> dict:
        """Process an API response, raising appropriate HTTP exceptions on error."""
        if response.is_success:
            return response.json()

        try:
            error_data = response.json()
        except Exception:
            error_data = {"error": {"message": response.text}}

        error_message = (
            error_data.get("error", {}).get("message", "Unknown WhatsApp API error")
        )

        if 400 <= response.status_code < 500:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"WhatsApp API error: {error_message}",
            )
        raise HTTPException(
            status_code=502,
            detail=f"WhatsApp API upstream error: {error_message}",
        )

    async def send_template_message(
        self,
        to: str,
        template_name: str,
        language_code: str = "en_US",
        components: list | None = None,
    ) -> dict:
        """Send a template message. Returns the API response."""
        payload: dict = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components is not None:
            payload["template"]["components"] = components

        try:
            response = await self._http.post(
                f"{self.base_url}/messages",
                headers=self.headers,
                json=payload,
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail="WhatsApp API request timed out",
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to WhatsApp API",
            )

        return await self._handle_response(response)

    async def send_text_message(self, to: str, body: str) -> dict:
        """Send a free-form text message (only works within 24h conversation window).

        Returns the API response.
        """
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }

        try:
            response = await self._http.post(
                f"{self.base_url}/messages",
                headers=self.headers,
                json=payload,
            )
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail="WhatsApp API request timed out",
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to WhatsApp API",
            )

        return await self._handle_response(response)

    async def get_templates(self, business_account_id: str) -> list[dict]:
        """Fetch available message templates from the business account."""
        url = (
            f"https://graph.facebook.com/{self.api_version}"
            f"/{business_account_id}/message_templates"
        )

        try:
            response = await self._http.get(url, headers=self.headers)
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail="WhatsApp API request timed out",
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to WhatsApp API",
            )

        data = await self._handle_response(response)
        return data.get("data", [])

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()


def get_whatsapp_client() -> WhatsAppClient:
    """FastAPI dependency. Raises 503 if not configured."""
    if not settings.whatsapp_api_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=503,
            detail="WhatsApp service not configured",
        )
    return WhatsAppClient(
        api_token=settings.whatsapp_api_token,
        phone_number_id=settings.whatsapp_phone_number_id,
        api_version=settings.whatsapp_api_version,
    )
