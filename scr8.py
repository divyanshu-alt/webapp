import argparse
import csv
import re
import time
import os
from difflib import SequenceMatcher
from typing import Dict, Optional

from googleapiclient.discovery import build
from indic_transliteration import sanscript
from indic_transliteration.sanscript import SchemeMap, SCHEMES, transliterate
from youtubesearchpython import VideosSearch, CustomSearch, VideoDurationFilter


def parse_args():
    parser = argparse.ArgumentParser(description='Search YouTube for movies and update CSV.')
    parser.add_argument('input_csv', help='Input CSV file path')
    parser.add_argument('--use-api', action='store_true', help='Use YouTube API (requires API key)')
    parser.add_argument('--api-key', help='YouTube API key (required if using API)')
    parser.add_argument('--output-csv', default='output.csv', help='Output CSV file path')
    parser.add_argument('--batch-size', type=int, help='Number of rows to process in each batch')
    parser.add_argument('--batch-index', type=int, help='Index of the current batch (0-based)')
    return parser.parse_args()


def initialize_output(output_csv, fieldnames):
    """Create output file with headers if it doesn't exist"""
    if not os.path.exists(output_csv):
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()


def get_processed_ids(output_csv):
    """Get set of already processed IDs"""
    processed = set()
    if os.path.exists(output_csv):
        with open(output_csv, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                processed = {row['ID'] for row in reader}
    return processed


def clean_year(year_str: str) -> str:
    """Extract 4-digit year from string with possible Roman numerals"""
    match = re.search(r'\d{4}', year_str)
    return match.group(0) if match else year_str


def format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes:02d}:{seconds:02d}"


def normalize_text(text: str) -> str:
    """Normalize and transliterate text for better comparison"""
    # Remove common phrases and special characters
    text = re.sub(r'(full movie|hd|official|पूरी फिल्म)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[^a-zA-Z0-9\u0900-\u097F ]', '', text).strip()
    
    # Detect Devanagari script and transliterate to Latin
    if re.search(r'[\u0900-\u097F]', text):
        text = transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)
    
    return text.lower()


def contains_foreign_script(text: str) -> bool:
    """Check for non-English/Hindi characters after removing decorations"""
    # First remove all decorative characters
    decorations = r'[♤☆♥♦♣♠•●■►▼▲►▼◄►▼►►▼◄►▼►►▼◄►▼►►▼◄►▼►►▼◄►▼►►▼◄►▼》→←↑↓↔↕↨©®™°²³‰§¶¥¢£€]'
    clean_text = re.sub(decorations, '', text)
    
    # Remove all punctuation/symbols except basic ones
    clean_text = re.sub(r'[^\w\u0900-\u097F\s\-\|]', '', clean_text)
    
    # Check remaining text
    foreign_pattern = re.compile(r'[^\u0000-\u00FF\u0900-\u097F]')
    return bool(foreign_pattern.search(clean_text))

def title_similarity(a: str, b: str) -> float:
    """Calculate similarity with better decorative character handling"""
    # Apply penalty only if core text contains foreign scripts
    core_text = re.sub(r'[^\w\u0900-\u097F\s]', '', b)  # Remove all non-word chars
    foreign_penalty = 0.7 if contains_foreign_script(core_text) else 1.0
    
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    
    seq_match = SequenceMatcher(None, a_norm, b_norm).ratio()
    a_words = set(a_norm.split())
    b_words = set(b_norm.split())
    word_overlap = len(a_words & b_words) / max(len(a_words), 1)
    
    base_score = (seq_match * 0.7) + (word_overlap * 0.3)
    return base_score * foreign_penalty



def title_similarity(a: str, b: str) -> float:
    """Calculate similarity score with transliteration support"""
    core_text = re.sub(r'[^\w\u0900-\u097F\s]', '', b)  # Remove all non-word chars
    foreign_penalty = 0.5 if contains_foreign_script(core_text) else 1.0

    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    
    # Calculate similarity using multiple methods
    seq_match = SequenceMatcher(None, a_norm, b_norm).ratio()
    
    # Additional check for contained words
    a_words = set(a_norm.split())
    b_words = set(b_norm.split())
    word_overlap = len(a_words & b_words) / max(len(a_words), 1)
    
    return ((seq_match * 0.7) + (word_overlap * 0.3)) * foreign_penalty


def get_best_thumbnail(thumbnails: dict) -> str:
    for quality in ['maxres', 'high', 'medium', 'standard', 'default']:
        if thumbnails.get(quality):
            return thumbnails[quality]['url']
    return ''


def iso8601_to_seconds(duration: str) -> int:
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = int(match.group(3)) if match.group(3) else 0
    return hours * 3600 + minutes * 60 + seconds


def parse_duration(duration_str: str) -> int:
    if not duration_str or duration_str.strip() in ['-', '']:
        return 0
    parts = list(map(int, re.findall(r'\d+', duration_str)))
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 1:
        return parts[0] * 60  # Assume minutes
    return 0


def search_youtube_api(movie_name: str, year: str, api_key: str) -> Optional[Dict]:
    youtube = build('youtube', 'v3', developerKey=api_key)
    base_query = f"{movie_name} {clean_year(year)} full movie -songs -lyrics -album -scene"
    print(f"\n[DEBUG] API Search Query: {base_query}")
    
    try:
        search_params = {
            'q': base_query,
            'part': 'id,snippet',
            'type': 'video',
            'maxResults': 10,
            'videoDuration': 'long'
        }
        search_response = youtube.search().list(**search_params).execute()
        video_ids = [item['id']['videoId'] for item in search_response.get('items', [])]
        
        if not video_ids:
            return None

        videos_params = {
            'part': 'contentDetails,snippet',
            'id': ','.join(video_ids)
        }
        videos_response = youtube.videos().list(**videos_params).execute()
    except Exception as e:
        print(f"API Error: {e}")
        return None

    best_video = None
    best_score = -1

    for video in videos_response.get('items', []):
        video_title = video['snippet']['title']
        duration_sec = iso8601_to_seconds(video['contentDetails']['duration'])
        
        # Calculate scores
        similarity_score = title_similarity(movie_name, video_title)
        duration_score = min(duration_sec / 7200, 1.0)
        total_score = (similarity_score * 0.8) + (duration_score * 0.2)
        
        print(f"\n[DEBUG] Original: {movie_name} | YouTube: {video_title}")
        print(f"        Normalized: {normalize_text(movie_name)} vs {normalize_text(video_title)}")
        print(f"        Similarity: {similarity_score:.2f} | Duration: {format_duration(duration_sec)}")
        print(f"        Total Score: {total_score:.2f}")

        if total_score > best_score and similarity_score > 0.25:
            best_score = total_score
            best_video = {
                'title': video_title,
                'link': f"https://www.youtube.com/watch?v={video['id']}",
                'duration': duration_sec,
                'thumbnail': get_best_thumbnail(video['snippet']['thumbnails']),
                'channel': 'tofill',
                'views': 404
            }

    return best_video

def search_youtube_noapi(movie_name: str, year: str) -> Optional[Dict]:
    base_query = f"{movie_name} {clean_year(year)} full movie -songs -lyrics -album"
    print(f"\n[DEBUG] Non-API Search Query: {base_query}")
    
    try:
        videos_search = CustomSearch(base_query, VideoDurationFilter.long, limit=10)
        results = videos_search.result()['result']
    except Exception as e:
        print(f"Search Error: {e}")
        return None

    best_video = None
    best_score = -1

    for video in results:
        video_title = video['title']
        duration_sec = parse_duration(video.get('duration', '0:00'))
        
        # Calculate scores
        similarity_score = title_similarity(movie_name, video_title)
        duration_score = min(duration_sec / 7200, 1.0)
        total_score = (similarity_score * 0.8) + (duration_score * 0.2)
        
        print(f"\n[DEBUG] Original: {movie_name} | Video: {video_title}")
        print(f"        Normalized: {normalize_text(movie_name)} vs {normalize_text(video_title)}") 
        print(f"        Similarity: {similarity_score:.2f} | Duration: {format_duration(duration_sec)}")
        print(f"        Total Score: {total_score:.2f}")

        if total_score > best_score:
            best_score = total_score
            best_video = {
                'title': video_title,
                'link': video['link'],
                'duration': duration_sec,
                'thumbnail': video['thumbnails'][-1]['url'] if video['thumbnails'] else '',
                'channel': video['channel']['name'] if video['channel'] else '',
                'views': video['viewCount']['text']
            }

    return best_video


def process_csv(args):
    processed_ids = get_processed_ids(args.output_csv)

    with open(args.input_csv, 'r', newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames + [
            'YouTube Link', 
            'Video Title',
            'Duration (HH:MM:SS)', 
            'Thumbnail',
            'Channel',
            'Views'
        ]

        initialize_output(args.output_csv, fieldnames)

        # Batch processing
        all_rows = [row for row in reader if row['ID'] not in processed_ids]
        total_rows = len(all_rows)
        
        start = 0
        end = total_rows
        rows = all_rows
        if args.batch_size is not None and args.batch_index is not None:
            start = args.batch_index * args.batch_size
            end = start + args.batch_size
            rows = all_rows[start:end]

        for i, row in enumerate(rows):
            if row['ID'] in processed_ids:
                print(f"Skipping already processed: {row['ID']}")
                continue

            print(f"\nProcessing {start + i + 1}/{len(rows) + start}: {row['Movie Name']} ({row['Year']})")
            
            video_info = None
            try:
                if args.use_api:
                    video_info = search_youtube_api(row['Movie Name'], row['Year'], args.api_key)
                else:
                    video_info = search_youtube_noapi(row['Movie Name'], row['Year'])
            except Exception as e:
                print(f"Processing Error: {e}")

            output_row = {
                **row,
                'YouTube Link': video_info.get('link', '') if video_info else '',
                'Video Title': video_info.get('title', '') if video_info else '',
                'Duration (HH:MM:SS)': format_duration(video_info.get('duration', 0)) if video_info else '',
                'Thumbnail': video_info.get('thumbnail', '') if video_info else '',
                'Channel': video_info.get('channel', '') if video_info else '',
                'Views': video_info.get('views', '') if video_info else ''
            }

            output_row = None
            if video_info:
                output_row = {
                    **row,
                    'YouTube Link': video_info.get('link', ''),
                    'Video Title': video_info.get('title', ''),
                    'Duration (HH:MM:SS)': format_duration(video_info.get('duration', 0)),
                    'Thumbnail': video_info.get('thumbnail', ''),
                    'Channel': video_info.get('channel', ''),
                    'Views': video_info.get('views', '')
                }
                print(f"\n✅ Found: {video_info['title']}")
                print(f"   Link: {video_info['link']}")
                print(f"   Duration: {video_info['duration']}")
                print(f"   Thumbnail: {video_info['thumbnail']}")
            else:
                output_row = {
                    **row,
                    'YouTube Link': '',
                    'Video Title': '',
                    'Duration (HH:MM:SS)': '',
                    'Thumbnail': '',
                    'Channel': '',
                    'Views': ''
                }
                print("❌ No suitable video found")

            with open(args.output_csv, 'a', newline='', encoding='utf-8') as outfile:
                writer = csv.DictWriter(outfile, fieldnames=fieldnames)
                writer.writerow(output_row)

            processed_ids.add(row['ID'])
            print(f"Saved results for {row['ID']}")
            time.sleep(2)

def main():
    args = parse_args()
    process_csv(args)


if __name__ == '__main__':
    main()

