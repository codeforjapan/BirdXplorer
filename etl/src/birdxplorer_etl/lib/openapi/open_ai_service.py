from birdxplorer_etl.settings import OPENAPI_TOKEN
from birdxplorer_etl.lib.ai_model.ai_model_interface_base import AIModelInterface
from birdxplorer_common.storage import LanguageIdentifier
from openai import OpenAI


class OpenAIService(AIModelInterface):
    def __init__(self):
        self.api_key = OPENAPI_TOKEN
        self.client = OpenAI(
            api_key=self.api_key
        )

    def detect_language(self, text: str) -> str:
        prompt = (
            "Detect the language of the following text and return only the language code "
            f"from this list: en, es, ja, pt, de, fr. Text: {text}. "
            "Respond with only the language code, nothing else."
        )

        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            seed=1,
            max_tokens=30
        )

        message_content = response.choices[0].message.content.strip()

        if message_content in LanguageIdentifier._value2member_map_:
            return LanguageIdentifier(message_content)

        valid_code = next((code for code in LanguageIdentifier._value2member_map_ if code in message_content), None)

        if valid_code:
            return LanguageIdentifier(valid_code)

        raise ValueError(f"Invali　３d language code received: {message_content}")