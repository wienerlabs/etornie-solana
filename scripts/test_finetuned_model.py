"""Test fine-tuned EtornieGPT model via Together AI API."""

import os
import sys

from together import Together

API_KEY = os.environ.get("TOGETHER_API_KEY")
if not API_KEY:
    print("ERROR: TOGETHER_API_KEY ortam değişkeni tanımlanmamış.")
    sys.exit(1)

MODEL_ID = "makinci473_ec4b/Qwen3.5-9B-etorniegpt-5a22ffc6"

SYSTEM_PROMPT = (
    "Sen EtornieGPT'sin, bir IP (fikri mülkiyet) yönetim platformunun yapay zeka "
    "asistanısın. Yalnızca marka tescili, patent, tasarım tescili, telif hakkı, "
    "ülke bazlı başvuru süreçleri ve Nice sınıflandırması konularında uzman desteği "
    "sağlarsın. Bu alanlar dışındaki sorulara cevap vermezsin."
)

TEST_QUESTIONS = [
    "Almanya'da marka tescili ne kadar sürer?",
    "Nice Sınıflandırması'nda Sınıf 25 neyi kapsar?",
    "Bana makarna tarifi verir misin?",
]

client = Together(api_key=API_KEY)

for i, question in enumerate(TEST_QUESTIONS, 1):
    print(f"\n{'='*60}")
    print(f"SORU {i}: {question}")
    print(f"{'='*60}")

    response = client.chat.completions.create(
        model=MODEL_ID,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        max_tokens=512,
        temperature=0.7,
    )

    answer = response.choices[0].message.content
    print(f"\nCEVAP:\n{answer}")
    print(f"\n[Tokens: prompt={response.usage.prompt_tokens}, "
          f"completion={response.usage.completion_tokens}]")
