import re
import random

def parse_spintax(text: str) -> str:
    """Parses spintax like {Hello|Hi|Hey} and picks a random value."""
    while True:
        match = re.search(r'\{([^{}]*)\}', text)
        if not match:
            break
        options = match.group(1).split('|')
        text = text[:match.start()] + random.choice(options) + text[match.end():]
    return text
