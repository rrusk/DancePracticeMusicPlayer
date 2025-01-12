#!/usr/bin/sh
# Note: used gpick to match background color of icons to text buttons
# From https://www.svgrepo.com/svg/107252/music-play-button?edit=true, Icon size 200px, padding 35%
convert +negate -background "rgb(18,53,70)" -resize 48x48 music-play-button-svgrepo-com.svg play.png
# From https://www.svgrepo.com/svg/424370/media-player-music-pause?edit=true, Icon size 200px, padding 35%
convert +negate -background "rgb(18,53,70)" -resize 48x48 media-player-music-pause-svgrepo-com.svg pause.png
#From https://www.svgrepo.com/svg/424374/music-player-stop?edit=true
convert +negate -background "rgb(18,53,70)" -resize 48x48 music-player-stop-svgrepo-com.svg stop.png
#convert +negate -background "rgb(18,53,70)" -resize 48x48 IEC_60417_-_Ref-No_5125A.svg replay.png
convert +negate -background "rgb(18,53,70)" -resize 48x48 replay.svg replay.png
mv play.png pause.png stop.png replay.png ../
