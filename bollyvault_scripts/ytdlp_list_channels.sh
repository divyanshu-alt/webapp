#!/bin/bash

# Loop through each line in channels.txt
while IFS= read -r channel; do
    # Run yt-dlp to get video metadata for each channel, filtering by duration > 3600 seconds
    yt-dlp -j --flat-playlist --match-filter "duration>3600" "$channel" > "${channel//[^a-zA-Z0-9]/_}_videos.json"
done < channels.txt
