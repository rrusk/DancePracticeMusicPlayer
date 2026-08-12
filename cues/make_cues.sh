#!/bin/bash
# Generates the cue audio used by competition-round practice types.
#
# A cue is an ordinary audio file that the player drops into the playlist and
# plays to its natural length, so gaps and warnings need no special handling
# during playback -- pause, seek and the progress bar all work as usual.
#
#   gap_20.ogg     20s of silence, between dances within a round.
#   round_gap.ogg  2:00 between rounds, silent except for a 5s brass warning
#                  starting at 1:40 so dancers are ready when the music starts.
#
# The warning replaces the DJ's original approach of silencing a Paso Doble
# except for a strident trumpet bit. It is synthesised here so the file can be
# regenerated and redistributed without borrowing from a commercial recording.
#
# Requires ffmpeg. Run from this directory:  ./make_cues.sh

set -e
cd "$(dirname "$0")"

RATE=44100
QUALITY=4          # ogg vorbis quality; these are near-silent so it stays tiny
GAP_SECONDS=20
ROUND_GAP_SECONDS=120
WARNING_AT=100     # 1 min 40 sec
WARNING_LENGTH=5

echo "Generating gap_20.ogg (${GAP_SECONDS}s silence)..."
ffmpeg -y -loglevel error \
    -f lavfi -i "anullsrc=r=${RATE}:cl=mono" \
    -t "${GAP_SECONDS}" -c:a libvorbis -q:a "${QUALITY}" gap_20.ogg

# The warning: a three-note rising brass-like fanfare. Each note is a sawtooth-ish
# stack of harmonics with a fast attack, which is what makes it cut through a
# noisy room. Deliberately not pretty.
note() {   # note <freq> <start> <duration>
    local f=$1 start=$2 dur=$3
    echo "sin(2*PI*${f}*t)*0.45 \
        + sin(2*PI*${f}*2*t)*0.30 \
        + sin(2*PI*${f}*3*t)*0.20 \
        + sin(2*PI*${f}*4*t)*0.12 \
        + sin(2*PI*${f}*5*t)*0.07"
}

echo "Generating round_gap.ogg (${ROUND_GAP_SECONDS}s, warning at ${WARNING_AT}s)..."

# Build the 5s fanfare separately, then lay it into the silence at WARNING_AT.
ffmpeg -y -loglevel error -f lavfi \
    -i "aevalsrc='($(note 466 0 0))*between(t,0.0,1.1)*min(1,t/0.02)*max(0,1-max(0,t-0.9)/0.2) \
                + ($(note 587 0 0))*between(t,1.2,2.3)*min(1,(t-1.2)/0.02)*max(0,1-max(0,t-2.1)/0.2) \
                + ($(note 698 0 0))*between(t,2.4,4.6)*min(1,(t-2.4)/0.02)*max(0,1-max(0,t-3.6)/1.0)' \
        :s=${RATE}:d=${WARNING_LENGTH}" \
    -af "tremolo=f=6:d=0.25,highpass=f=180,alimiter=limit=0.85" \
    -c:a pcm_s16le -f wav /tmp/_cue_warning.wav

ffmpeg -y -loglevel error \
    -f lavfi -i "anullsrc=r=${RATE}:cl=mono" \
    -i /tmp/_cue_warning.wav \
    -filter_complex "[1:a]adelay=${WARNING_AT}000|${WARNING_AT}000[w];[0:a][w]amix=inputs=2:duration=first:dropout_transition=0[out]" \
    -map "[out]" -t "${ROUND_GAP_SECONDS}" -c:a libvorbis -q:a "${QUALITY}" round_gap.ogg

rm -f /tmp/_cue_warning.wav

echo
ls -la gap_20.ogg round_gap.ogg
