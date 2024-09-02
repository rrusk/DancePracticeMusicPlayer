#!/usr/bin/env python

from gtts import gTTS
dances = ["Mambo"]
for dance in dances:
    if dance == "Mambo":
        dance_announced = "Mambo Number Five"
    else:
        dance_announced = dance
    tts_en1 = gTTS('  Please get ready for the ' + dance_announced + ' line dance. ', lang='en')
    tts_en2 = gTTS('  This song is from the German musician Lou Bega\'s album A Little Bit of Mambo.  ', lang='en')
    tts_en3 = gTTS('  Are you ready for ' + dance_announced + '? ', lang='en')
    with open(dance+'.mp3', 'wb') as f:
        tts_en1.write_to_fp(f)
        tts_en2.write_to_fp(f)
        tts_en3.write_to_fp(f)
