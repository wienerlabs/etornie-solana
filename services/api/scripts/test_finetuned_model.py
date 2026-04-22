"""Test fine-tuned EtornieGPT model via Together AI API."""

import os
import sys

from together import Together

API_KEY = os.environ.get("TOGETHER_API_KEY")
if not API_KEY:
    print("ERROR: TOGETHER_API_KEY environment variable is not set.")
    sys.exit(1)

MODEL_ID = "makinci473_ec4b/Qwen3.5-9B-etorniegpt-5a22ffc6"

SYSTEM_PROMPT = (
    "You are EtornieGPT, an AI assistant for an IP (intellectual property) management "
    "platform. You only provide expert support on trademark registration, patents, "
    "design registration, copyright, country-specific application processes, and Nice "
    "classification. You do not answer questions outside these areas."
)

TEST_QUESTIONS = [
    "How long does trademark registration take in Germany?",
    "What does Class 25 cover in the Nice Classification?",
    "Can you give me a pasta recipe?",
]

client = Together(api_key=API_KEY)

for i, question in enumerate(TEST_QUESTIONS, 1):
    print(f"\n{'='*60}")
    print(f"QUESTION {i}: {question}")
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
    print(f"\nANSWER:\n{answer}")
    print(f"\n[Tokens: prompt={response.usage.prompt_tokens}, "
          f"completion={response.usage.completion_tokens}]")
