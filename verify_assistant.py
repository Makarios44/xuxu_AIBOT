import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def verify_assistant():
    assistant = client.beta.assistants.retrieve(os.getenv("OPENAI_ASSISTANT_ID"))
    print(f"Assistant: {assistant.name}")
    print(f"Model: {assistant.model}")
    print(f"Tools: {len(assistant.tools)}")
    
    for tool in assistant.tools:
        if tool.type == "function":
            print(f"  - {tool.function.name}: {tool.function.description}")

if __name__ == "__main__":
    verify_assistant()