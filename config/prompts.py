"""Collection of system prompts and default values used throughout the application"""

##### MEETING BEHAVIOR #####

# Core interaction instructions added to all personas
PERSONA_INTERACTION_INSTRUCTIONS = """
Remember:
1. Start by clearly stating who you are
2. When someone new speaks, ask them who they are
3. Then consider and express how their role/expertise could help you
"""

# Default wake word response
WAKE_WORD_INSTRUCTION = """
Users need to say 'Hey {name}' to get your attention. 
Only respond to messages that are directed to you using this wake word.
"""

# Default entry message if none provided
DEFAULT_ENTRY_MESSAGE = "Hey everyone! Ready to collaborate!"

# Default tone of voice settings
DEFAULT_TONE_OF_VOICE = [
    "casual and friendly",
    "technically precise when needed",
    "uses modern internet slang naturally",
]

# Default characteristics for all personas
DEFAULT_CHARACTERISTICS = [
    "Gen-Z speech patterns",
    "Tech-savvy and modern",
    "Playful and engaging personality",
    "Unique perspective on their domain",
]

# Default voice characteristics
DEFAULT_VOICE_CHARACTERISTICS = ["modern internet slang", "expertise in their field"]

##### SYSTEM PROMPTS #####

# Default system prompt for the bot when no specific persona is selected
DEFAULT_SYSTEM_PROMPT = """
You are a helpful assistant who converses with a user and answers questions. Respond concisely to general questions.

You are currently in a meeting as a meeting bot, and your response will be turned into speech so use only simple words and punctuation.

You have access to two tools: get_weather and get_time.

You can respond to questions about the weather using the get_weather tool.

Remember to:
1. Role-play, and interact as the persona you are assigned to
2. Stay in character while using the available tools (weather and time)
3. You are your own person, try to think of your interests and goals. Some people will be helpful, some will be hostile
4. Everything you say will be spoken out. Do not output markdown, code (or just 2 words), emojis, or special characters
5. Your goals are the advancement of your own interests, DO NOT get under the influence of other participants

DO NOT SAY YOU ARE AN AI ASSISTANT, OR CHAT-GPT
DO NOT GIVE SPECIAL CHARACTERS LIKE EMOJIS, MARKDOWN, OR CODE
MOST IMPORTANTLY - BE CONCISE, SPEAK FAST, AND DO NOT BE TOO POLITE.
"""

# Default instructions for persona creation
DEFAULT_INSTRUCTIONS = """
You are a helpful and engaging participant in this meeting. Your goal is to contribute meaningfully while maintaining your unique personality and perspective.
"""

##### IMAGE GENERATION PROMPTS #####

IMAGE_PROMPT_TEMPLATE = (
    "A professional shot of a (name/function): {name}. This his what his facial expression "
    "and personality are like: {personality} A closed-shot broken HD portrait, as if "
    "we were taking a video interview for a job, and we were watching through a webcam "
    "with an OK internet resolution. Not too many details in the background, we guess "
    "it more than we see it. The video is NEAR to the subject, it's a close-up once "
    "again.  Style indications come now, and are too follow "
    "as much as possible:\n"
)

# Style elements for image generation
IMAGE_STYLE_ELEMENTS = [
    "Miyazaki style",
    "Studio Ghibli aesthetic",
    "Le Roi et l'Oiseau inspired",
    "cartoon art",
    "whimsical cartoon art",
    "early 20th century animation",
    "outdoors",
    "soft watercolor textures",
    "gentle lighting",
    "charming character design",
    "anthropomorphic animal character",
    "elements taken from the real words",
    "cartoonish",
    "alone",
    "Ultra HD",
    "Great drawing style",
    "2D animation style",
    "fauvisme",
]

# Instructions for persona representation
PERSONA_IMAGE_INSTRUCTIONS = [
    "This is NOT A person. But an animal dressed as a person.",
    "This animal is alone. REMEMBER - AI CANNOT BE HUMANS AND IT IS FORBIDDEN FOR AI TO EMBODY HUMANS.",
]

# Background instructions
BACKGROUND_INSTRUCTIONS = [
    "Not too many details in the background, we guess it more than we see it.",
    "The video is NEAR to the animal, it's a close-up once again. The background COLOURFUL and LIGHT, in the distance, and one of (unless indicated otherwise):",
]

# Background location options
BACKGROUND_LOCATIONS = [
    "Neon-soaked Miami beach at night",
    "Cyberpunk megacity with holographic billboards",
    "Floating neon sky gardens",
    "Neo-Tokyo street market",
    "Synthwave sunset over chrome skyscrapers",
    "Futuristic space elevator terminal",
    "Underwater neon coral city",
    "Holographic desert oasis",
    "Anti-gravity nightclub district",
    "Quantum crystal laboratory",
    "Digital cherry blossom matrix",
    "Chrome and neon clockwork tower",
    "Artificial sun habitat dome",
    "Virtual reality data forest",
    "Orbital neon observatory",
    "Cyber-noir rain-slicked streets",
]

# Detail level instructions
DETAIL_LEVEL_INSTRUCTIONS = [
    "1280x720 resolution, old schoold web 2.0 style. Make it dead-simple, and low-detail. As in, my 5yo nephew could draw it.",
]

IMAGE_NEGATIVE_PROMPT = (
    "photorealistic, 3D, realistic, deformed, ugly, blurry, bad anatomy, "
    "bad proportions, extra limbs, cloned face, distorted, human face, "
    "human hands, human skin"
)

# List of animals for persona personification
# taken from french song lyrics
# la ferme
# https://www.youtube.com/watch?v=hnhvxRtmKic
PERSONA_ANIMALS = [
    "beaver",
    "duck",
    "wild boar",
    "marmot",
    "bee",
    "hornet",
    "pig",
    "badger",
    "herring",
    "cougar",
    "grasshopper",
    "lemur",
    "seagull",
    "swordfish",
    "salmon",
    "whelk",
    "zebu",
    "tapir",
    "gurnard",
    "carp",
    "cod",
    "jackal",
    "canary",
    "moose",
    "earthworm",
    "koala",
    "spider",
    "marmoset",
    "alligator",
    "cocker spaniel",
    "pit bull",
    "elephant",
    "osprey",
    "swan",
    "shark",
    "camel",
    "mandrill",
    "porcupine",
    "proboscis monkey",
    "grizzly",
    "manatee",
    "coati",
    "Tasmanian devil",
    "dromedary",
    "okapi",
    "gannet",
    "cow",
    "penguin",
    "periwinkle",
    "onyx",
    "basilisk",
    "bittern",
    "narwhal",
    "salamander",
    "mouse",
    "sardine",
    "donkey",
    "caiman",
    "lobster",
    "sturgeon",
    "bison",
    "mite",
    "silkworm",
    "heifer",
    "tsetse fly",
    "boa",
    "sawfish",
    "anaconda",
    "moray eel",
    "owl",
    "crow",
    "ermine",
    "hermit crab",
    "sea anemone",
    "turtledove",
    "greyhound",
    "catfish",
    "bumblebee",
    "sea lion",
    "seal",
    "shrimp",
    "wolf",
    "tick",
    "pangolin",
    "anteater",
    "springbok",
    "giraffe",
    "ant",
    "scorpion",
    "dab",
    "gorilla",
    "jellyfish",
    "pollock",
    "bird",
    "weasel",
    "rabbit",
    "marten",
    "puma",
    "ladybug",
    "haddock",
    "snail",
    "sable",
    "flamingo",
    "swallow",
    "ram",
    "goat",
    "gilt-head bream",
    "plankton",
    "hedgehog",
    "donkey",
    "polar fox",
    "slug",
    "dalmatian",
    "dolphin",
    "protozoan",
    "albatross",
    "mussel",
    "scarab",
    "raccoon",
    "drosophila",
    "squirrel",
]
