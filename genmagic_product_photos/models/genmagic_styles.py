"""The photo styles and the prompt each one sends. Every style tells the service to keep the
product exactly as it is."""
import re

MAX_EXTRA_LENGTH = 300
DEFAULT_STYLE = 'studio'

_KEEP = (
    "Keep the product itself exactly as in the photo: same shape, colors, materials, label, "
    "logo and proportions."
)

STYLE_LABELS = [
    ('studio', "White studio"),
    ('lifestyle', "Lifestyle scene"),
    ('model', "With a model"),
    ('flatlay', "Flat lay"),
    ('seasonal', "Seasonal"),
]

STYLE_PROMPTS = {
    'studio': (
        "Professional e-commerce product photo on a clean white seamless background, "
        "soft studio lighting, gentle shadow. " + _KEEP
    ),
    'lifestyle': (
        "Lifestyle product photo of this product in a tasteful real-life setting where it is "
        "used, natural light, shallow depth of field. " + _KEEP
    ),
    'model': (
        "A person naturally using or wearing this product in a bright, modern setting, "
        "editorial photo. " + _KEEP
    ),
    'flatlay': (
        "Top-down flat lay product photo with complementary props on a styled surface, "
        "even soft light. " + _KEEP
    ),
    'seasonal': (
        "Seasonal holiday product photo with festive but uncluttered decoration around the "
        "product, warm light. " + _KEEP
    ),
}


def clean_extra(extra):
    """Plain text of the merchant's own words, cut to the allowed length."""
    text = re.sub(r'<[^>]*>', '', extra or '')
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    return text.strip()[:MAX_EXTRA_LENGTH]


def build_prompt(style, extra):
    """The prompt for a style plus the merchant's own words (at most 300 characters)."""
    base = STYLE_PROMPTS.get(style) or STYLE_PROMPTS[DEFAULT_STYLE]
    more = clean_extra(extra)
    return base + ' ' + more if more else base
