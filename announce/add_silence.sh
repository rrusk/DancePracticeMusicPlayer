#!/bin/sh
# Pads the generated announcements and encodes what the player actually loads.
#
# announce_dance.py writes <Dance>.mp3 from gTTS with no silence around the
# speech. This adds two seconds each side so an announcement neither clips the
# preceding song nor runs straight into the next one, gives Paso Doble a much
# longer tail so dancers have time to take up the opening position, and then
# produces the matching .ogg.
#
# That last step matters: the player loads <Dance>.ogg and never looks at the
# mp3. Leaving the conversion out of this script is how the Paso Doble padding
# came to be missing -- the mp3 was padded by hand and the ogg the player reads
# was not, so the extra time silently disappeared.
#
# Every dance is padded as though its mp3 came straight from announce_dance.py,
# so a dance is processed only when it has no .ogg, or its .mp3 is newer than
# its .ogg -- that is, when the mp3 has just been regenerated. Re-running does
# nothing, which is what keeps the padding from being applied twice. --force
# rebuilds everything and expects unpadded mp3s.
#
# Requires ffmpeg. sox is no longer needed: ffmpeg is already required to build
# the cues, and is available on Windows where sox usually is not.

set -e
cd "$(dirname "$0")"

LEAD_SECONDS=2
TRAIL_SECONDS=2
PASO_TOTAL_SECONDS=15   # "Paso Doble", then time to set the opening pose
QUALITY=4

FORCE=""
if [ "$1" = "--force" ]; then
    FORCE=yes
fi

for mp3 in *.mp3; do
    dance="${mp3%.mp3}"
    ogg="${dance}.ogg"

    if [ -z "$FORCE" ] && [ -f "$ogg" ] && [ ! "$mp3" -nt "$ogg" ]; then
        continue
    fi

    padded="${dance}.padded.mp3"
    if [ "$dance" = "PasoDoble" ]; then
        # Given as a total rather than "add 13 seconds", so the intent is
        # readable and a change to the lead does not silently change the tail.
        echo "Padding $mp3 to ${PASO_TOTAL_SECONDS}s so dancers can take position..."
        ffmpeg -y -loglevel error -i "$mp3" \
            -af "adelay=${LEAD_SECONDS}000:all=1,apad" -t "$PASO_TOTAL_SECONDS" \
            -c:a libmp3lame -q:a "$QUALITY" "$padded"
    else
        echo "Padding $mp3 with ${LEAD_SECONDS}s lead and ${TRAIL_SECONDS}s tail..."
        ffmpeg -y -loglevel error -i "$mp3" \
            -af "adelay=${LEAD_SECONDS}000:all=1,apad=pad_dur=${TRAIL_SECONDS}" \
            -c:a libmp3lame -q:a "$QUALITY" "$padded"
    fi
    mv "$padded" "$mp3"

    echo "  encoding $ogg, which is the file the player loads"
    ffmpeg -y -loglevel error -i "$mp3" -c:a libvorbis -q:a "$QUALITY" "$ogg"
done

echo "Done."
