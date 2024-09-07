#!/usr/bin/env python

from gtts import gTTS
dances = ["LineDance"]
for dance in dances:
    if dance == "LineDance":
        dance_announced = "Line Dance"
    else:
        dance_announced = dance
    tts_en1 = gTTS('  Please get ready for a ' + dance_announced, lang='en')
    tts_en2 = gTTS('  Are you ready for a ' + dance_announced + '? ', lang='en')
    with open(dance+'.mp3', 'wb') as f:
        tts_en1.write_to_fp(f)
        tts_en2.write_to_fp(f)
