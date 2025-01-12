#!/usr/bin/sh
# Note: used gpick to match background of icons to text buttons
convert +negate -background "rgb(18,53,70)" -resize 48x48 play-filled-alt.svg play.png
convert +negate -background "rgb(18,53,70)" -resize 48x48 pause-filled.svg pause.png
convert +negate -background "rgb(18,53,70)" -resize 48x48 stop.svg stop.png
convert +negate -background "rgb(18,53,70)" -resize 48x48 replay.svg replay.png
