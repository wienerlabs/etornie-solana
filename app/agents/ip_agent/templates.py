"""Configurable deadline notification message templates.

Templates are keyed by the number of days remaining until the deadline.
Each entry provides separate messages for the assigned lawyer and the client.

All text is in Turkish using plain ASCII characters (no special chars like
s-cedilla, c-cedilla, g-breve, etc.) because WhatsApp API handles encoding
and some carriers have issues with non-ASCII characters.
"""

DEADLINE_TEMPLATES: dict[int, dict[str, str]] = {
    30: {
        "lawyer": (
            "Sayin {lawyer_name}, {case_number} numarali ({case_title}) "
            "dava dosyanizin son tarihine 30 gun kalmistir. "
            "Lutfen gerekli islemleri planlayin. "
            "Son tarih: {deadline}"
        ),
        "client": (
            "Sayin {client_name}, {case_number} numarali ({case_title}) "
            "basvurunuzun son tarihine 30 gun kalmistir. "
            "Avukatiniz bilgilendirilmistir. "
            "Son tarih: {deadline}"
        ),
    },
    7: {
        "lawyer": (
            "HATIRLATMA: Sayin {lawyer_name}, {case_number} numarali ({case_title}) "
            "dava dosyanizin son tarihine 7 gun kalmistir. "
            "Acil islem gereklidir. "
            "Son tarih: {deadline}"
        ),
        "client": (
            "HATIRLATMA: Sayin {client_name}, {case_number} numarali ({case_title}) "
            "basvurunuzun son tarihine 7 gun kalmistir. "
            "Avukatiniz sureci takip etmektedir. "
            "Son tarih: {deadline}"
        ),
    },
    1: {
        "lawyer": (
            "ACIL: Sayin {lawyer_name}, {case_number} numarali ({case_title}) "
            "dava dosyanizin son tarihi YARIN! "
            "Bugune kadar islemlerin tamamlanmis olmasi gerekmektedir. "
            "Son tarih: {deadline}"
        ),
        "client": (
            "ACIL: Sayin {client_name}, {case_number} numarali ({case_title}) "
            "basvurunuzun son tarihi YARIN! "
            "Avukatiniz son islemleri gerceklestirmektedir. "
            "Son tarih: {deadline}"
        ),
    },
}
