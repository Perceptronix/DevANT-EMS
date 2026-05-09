import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

print("KEY:", os.getenv("GROQ_API_KEY"))

try:
    client = Groq(
        api_key=os.getenv("GROQ_API_KEY"),
    )
    model_name = os.getenv("GROQ_MODEL", "llama3-70b-8192")

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "user", "content": "Explain operational monitoring simply."}
        ]
    )

    print(response.choices[0].message.content)
except Exception as e:
    print(f"Error: {e}")
