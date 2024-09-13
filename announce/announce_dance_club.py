#!/usr/bin/env python

from gtts import gTTS
dances = ["AmericanRumba", "ArgentineTango", "Bolero", "DiscoFox", "Hustle", "LindyHop", "Mambo", "Merengue", "NC2Step", "Polka", "Salsa"]
for dance in dances:
    if dance == "AmericanRumba":
        dance_announced = "American Rumba"
    elif dance == "ArgentineTango":
        dance_announced = "Argentine Tango"
    elif dance == "LindyHop":
        dance_announced = "Lindy Hop"
    elif dance == "NC2Step":
        dance_announced = "Night Club Two Step"
    else:
        dance_announced = dance
    tts_en1 = gTTS('  Please get ready for ' + dance_announced, lang='en')
    tts_en2 = gTTS('  Be ready with your partner for ' + dance_announced, lang='en')
    with open(dance+'.mp3', 'wb') as f:
        tts_en1.write_to_fp(f)
        tts_en2.write_to_fp(f)
