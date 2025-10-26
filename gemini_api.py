import os

from google import genai
from google.genai import types
from dotenv import load_dotenv

def gemini_request():
    load_dotenv()
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") )

    myfile = client.files.upload(file="image.jpg")

    while True:
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",

            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                system_instruction=[
                    types.Part.from_text(text="""based on the images you will be given and a list of human scents : Fragrant (e.g., florals, perfumes)
        Woody (e.g., pine, fresh cut grass)
        Fruity (non-citrus)
        Chemical (e.g., ammonia, bleach)
        Minty (e.g., eucalyptus, camphor)
        Sweet (e.g., chocolate, vanilla, caramel)
        Popcorn (or toasted/nutty)
        Lemon (or citrus)
        Pungent (e.g., blue cheese, cigar smoke, sweat)
        Decayed (e.g., rotting meat, sour milk), generate a plain string with the scent characterization of the image in lowercase, attribute to the image the most accurate smell it will have, keeping in mind it's intensity and distance from the image perspective, if it is an image of a digital interface or any other situation that does not have smell return none, you are allowed to mix odors but keep in mind the proportions maximum number of odors shall be 2, both should have proportion in format of decimal number and the sum should compose 1, the response should be as quick as possible but also accurate, the final format should be consistent, a string with structure scent number scent number if there are 2 distinct scents if not only scent number """),
                ],
            ),
            contents=myfile,
        )
        return response.text

# print(gemini_request())