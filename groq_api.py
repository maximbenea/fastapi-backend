import os
import base64
from groq import Groq
from dotenv import load_dotenv

image_path = "image.jpg"

# Helper function to encode image to base64
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def groq_request():
    load_dotenv()
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    # Encode the image
    # (Groq/Llama needs the image sent as data, not an uploaded file ID)
    base64_image = encode_image("image.jpg")

    prompt_instruction = """
    based on the images you will be given and a list of human scents : Fragrant (e.g., florals, perfumes)
        Woody (e.g., pine, fresh cut grass)
        Fruity (non-citrus)
        Chemical (e.g., ammonia, bleach)
        Minty (e.g., eucalyptus, camphor)
        Sweet (e.g., chocolate, vanilla, caramel)
        Popcorn (or toasted/nutty)
        Lemon (or citrus)
        Pungent (e.g., blue cheese, cigar smoke, sweat)
        Decayed (e.g., rotting meat, sour milk), 
        generate a plain string with the scent characterization of the image in lowercase, attribute to the image the most accurate smell it will have, keeping in mind it's intensity and distance from the image perspective, if it is an image of a digital interface or any other situation that does not have smell return none, the response should be as quick as possible but also accurate, the final format should be consistent
        limit to one word!!!
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_instruction},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                            },
                        },
                    ],
                }
            ],
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0,

            # Llama models sometimes chat too much, so we limit tokens to ensure concise output
            max_completion_tokens=20,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"

#print(groq_request())