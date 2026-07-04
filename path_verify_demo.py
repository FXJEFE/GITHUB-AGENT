name = "path_verify_demo"
description = "Reverses the characters of an input string."
category = "String Processing"
parameters = {
    "text": {
        "type": "string",
        "description": "The input string to reverse",
        "required": True
    }
}

def run(**kwargs):
    text = kwargs.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    return {"reversed": text[::-1]}
