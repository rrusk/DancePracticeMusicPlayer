#!/usr/bin/env python

from gtts import gTTS
dances = ["Waltz", "Cha Cha"]
for dance in dances:
    dance_announced = dance
    tts_en1 = gTTS('  Please get ready for the ' + dance_announced, lang='en')
    tts_en2 = gTTS('  This will be a snowball dance, meaning that when the music pauses, find a new partner, preferably someone not yet dancing.', lang='en')
    tts_en3 = gTTS('  Are you ready for a ' + dance_announced + 'snowball dance? ', lang='en')
    with open(dance+'.mp3', 'wb') as f:
        tts_en1.write_to_fp(f)
        tts_en2.write_to_fp(f)
        tts_en3.write_to_fp(f)
