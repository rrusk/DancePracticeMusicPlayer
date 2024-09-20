#!/usr/bin/env python

import gtts
from gtts import gTTS
tts_en1 = gTTS('  Please get ready to dance. Be ready with your partner to dance.', lang='en')
with open('Generic.mp3', 'wb') as f:
    tts_en1.write_to_fp(f)
