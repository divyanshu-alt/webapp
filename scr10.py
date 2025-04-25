import argparse
import csv
import re
import time
import os
import pandas as pd
from difflib import SequenceMatcher
from typing import Dict, Optional, Any
from youtubesearchpython import VideosSearch, CustomSearch, VideoDurationFilter
from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate  # Added missing import

# Channel lists (to be populated later)
whitelisted_channels = []
blacklisted_channels = []

# Channel cache to reduce API calls
channel_cache = {}

def parse_args():
    parser = argparse.ArgumentParser(description='Search YouTube for movies and update CSV.')
    parser.add_argument('input_csv', help='Input CSV file path')
    parser.add_argument('--output-csv', default='output.csv', help='Output CSV file path')
    parser.add_argument('--batch-size', type=int, help='Number of rows to process in each batch')
    parser.add_argument('--batch-index', type=int, help='Index of the current batch (0-based)')
    return parser.parse_args()

def initialize_output(output_csv, fieldnames):
    if not os.path.exists(output_csv):
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

def get_processed_ids(output_csv):
    processed = set()
    if os.path.exists(output_csv):
        with open(output_csv, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames and 'imdb_id' in reader.fieldnames:
                processed = {row['imdb_id'] for row in reader}
    return processed

def read_channels_csv(filename):
    cache = {}
    if os.path.exists(filename):
        with open(filename, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cache[row['Channel ID']] = {
                    'name': row['Channel Name'],
                    'link': row['Channel Link'],
                    'subscribers': int(row['Subscribers']) if row['Subscribers'].strip() else None
                }
    return cache

def write_channels_csv(filename, cache):
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['Channel ID', 'Channel Name', 'Channel Link', 'Subscribers'])
        writer.writeheader()
        for channel_id, data in cache.items():
            writer.writerow({
                'Channel ID': channel_id,
                'Channel Name': data['name'],
                'Channel Link': data['link'],
                'Subscribers': data['subscribers'] if data['subscribers'] is not None else ''
            })

def clean_year(year_str: str) -> str:
    match = re.search(r'\d{4}', str(year_str))
    return match.group(0) if match else year_str

def format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours > 0 else f"{minutes:02d}:{seconds:02d}"

def normalize_text(text: str) -> str:
    text = re.sub(r'(full movie|hd|official|पूरी फिल्म)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[^a-zA-Z0-9\u0900-\u097F ]', '', text).strip()
    if re.search(r'[\u0900-\u097F]', text):
        text = transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)
    return text.lower()

def contains_foreign_script(text: str) -> bool:
    clean_text = re.sub(r'[♤☆♥♦♣♠•●■►▼▲►▼◄►▼►►▼◄►▼►►▼◄►▼►►▼◄►▼►►▼◄►▼》→←↑↓↔↕↨©®™°²³‰§¶¥¢£€]', '', text)
    clean_text = re.sub(r'[^\w\u0900-\u097F\s\-\|]', '', clean_text)
    foreign_pattern = re.compile(r'[^\u0000-\u00FF\u0900-\u097F]')
    return bool(foreign_pattern.search(clean_text))

def title_similarity(a: str, b: str) -> float:
    core_text = re.sub(r'[^\w\u0900-\u097F\s]', '', b)
    foreign_penalty = 0.5 if contains_foreign_script(core_text) else 1.0
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    seq_match = SequenceMatcher(None, a_norm, b_norm).ratio()
    a_words = set(a_norm.split())
    b_words = set(b_norm.split())
    word_overlap = len(a_words & b_words) / max(len(a_words), 1)
    return ((seq_match * 0.7) + (word_overlap * 0.3)) * foreign_penalty

def parse_duration(duration_str: str) -> int:
    """Convert duration string (HH:MM:SS or MM:SS) to total seconds"""
    try:
        parts = list(map(int, duration_str.split(':')))
        return sum(part * 60**i for i, part in enumerate(reversed(parts)))
    except:
        return 0

def search_youtube_noapi(movie_name: str, year: str) -> Optional[Dict]:
    base_query = f"{movie_name} {clean_year(year)} full movie -songs -lyrics -album"
    print(f"\n[DEBUG] Search Query: {base_query}")
    
    try:
        videos_search = CustomSearch(base_query, VideoDurationFilter.long, limit=10)
        results = videos_search.result()['result']
        print(f"[DEBUG] Found {len(results)} results")
    except Exception as e:
        print(f"Search Error: {e}")
        return None

    filtered_results = []
    for video in results:
        channel = video.get('channel', {})
        channel_id = channel.get('id', '')
        if channel_id in blacklisted_channels:
            print(f"[BLACKLIST] Skipping {video['title'][:50]}...")
            continue
        filtered_results.append(video)

    print(f"[DEBUG] {len(filtered_results)} results after blacklist filtering")

    whitelisted_videos = [v for v in filtered_results if v.get('channel', {}).get('id', '') in whitelisted_channels]
    if whitelisted_videos:
        video = whitelisted_videos[0]
        channel = video.get('channel', {})
        duration_sec = parse_duration(video.get('duration', '0:00'))
        similarity = title_similarity(movie_name, video['title'])
        duration_score = min(duration_sec / 7200, 1.0)
        total_score = (similarity * 0.8) + (duration_score * 0.2)
        
        print(f"[WHITELIST] Found match: {video['title'][:50]}... (Score: {total_score:.2f})")
        return {
            'title': video['title'],
            'link': video['link'],
            'duration': duration_sec,
            'thumbnail': video['thumbnails'][-1]['url'] if video['thumbnails'] else '',
            'channel': channel.get('name', ''),
            'channel_id': channel.get('id', ''),
            'views': video.get('viewCount', {}).get('text', ''),
            'similarity_score': similarity,
            'duration_score': duration_score,
            'total_score': total_score
        }

    best_video = None
    best_score = -1
    for idx, video in enumerate(filtered_results):
        title = video['title']
        duration_sec = parse_duration(video.get('duration', '0:00'))
        similarity = title_similarity(movie_name, title)
        duration_score = min(duration_sec / 7200, 1.0)
        total_score = (similarity * 0.8) + (duration_score * 0.2)
        
        print(f"[SCORING {idx+1}/{len(filtered_results)}] {title[:50]}... | Similarity: {similarity:.2f} | Duration: {duration_sec}s | Total: {total_score:.2f}")
        if total_score > best_score:
            best_score = total_score
            channel = video.get('channel', {})
            best_video = {
                'title': title,
                'link': video['link'],
                'duration': duration_sec,
                'thumbnail': video['thumbnails'][-1]['url'] if video['thumbnails'] else '',
                'channel': channel.get('name', ''),
                'channel_id': channel.get('id', ''),
                'views': video.get('viewCount', {}).get('text', ''),
                'similarity_score': similarity,
                'duration_score': duration_score,
                'total_score': total_score
            }

    if best_video:
        print(f"[BEST MATCH] Selected: {best_video['title'][:50]}... (Score: {best_score:.2f})")
    else:
        print("[WARNING] No suitable video found")

    return best_video

def process_csv(args):
    global channel_cache
    channels_csv = os.path.splitext(args.output_csv)[0] + '_channels.csv'
    channel_cache = read_channels_csv(channels_csv)
    processed_ids = get_processed_ids(args.output_csv)

    with open(args.input_csv, 'r', newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames + [
            'YouTube Link', 'Video Title', 'Duration (HH:MM:SS)', 'Thumbnail',
            'Channel', 'Channel ID', 'Channel Link', 'Subscribers', 'Relevance',
            'Similarity Score', 'Duration Score', 'Total Score', 'Views'
        ]
        initialize_output(args.output_csv, fieldnames)

        all_rows = [row for row in reader if row['imdb_id'] not in processed_ids]
        if args.batch_size and args.batch_index is not None:
            start = args.batch_index * args.batch_size
            all_rows = all_rows[start:start+args.batch_size]

        total_rows = len(all_rows)
        for idx, row in enumerate(all_rows, 1):
            print(f"\n[{idx}/{total_rows}] Processing {row['imdb_id']}: {row['title']}")
            video_info = None
            try:
                video_info = search_youtube_noapi(row['title'], row['year_of_release'])
            except Exception as e:
                print(f"Error: {e}")

            output_row = row.copy()
            if video_info:
                channel_id = video_info.get('channel_id', '')
                if channel_id and channel_id not in channel_cache:
                    print(f"[NEW CHANNEL] Adding {channel_id} to cache")
                    channel_cache[channel_id] = {
                        'name': video_info['channel'],
                        'link': f"https://www.youtube.com/channel/{channel_id}",
                        'subscribers': None
                    }

                subs = channel_cache.get(channel_id, {}).get('subscribers', 0)
                relevance = 'H' if channel_id in whitelisted_channels else 'M' if (subs or 0) >= 100000 else 'L'

                output_row.update({
                    'YouTube Link': video_info['link'],
                    'Video Title': video_info['title'],
                    'Duration (HH:MM:SS)': format_duration(video_info['duration']),
                    'Thumbnail': video_info['thumbnail'],
                    'Channel': video_info['channel'],
                    'Channel ID': channel_id,
                    'Channel Link': channel_cache.get(channel_id, {}).get('link', ''),
                    'Subscribers': channel_cache.get(channel_id, {}).get('subscribers', ''),
                    'Relevance': relevance,
                    'Similarity Score': video_info['similarity_score'],
                    'Duration Score': video_info['duration_score'],
                    'Total Score': video_info['total_score'],
                    'Views': video_info['views']
                })
                print(f"[SUCCESS] Found match for {row['title']}")
            else:
                output_row.update({
                    'YouTube Link': '', 'Video Title': '', 'Duration (HH:MM:SS)': '',
                    'Thumbnail': '', 'Channel': '', 'Channel ID': '', 'Channel Link': '',
                    'Subscribers': '', 'Relevance': '', 'Similarity Score': '',
                    'Duration Score': '', 'Total Score': '', 'Views': ''
                })
                print(f"[WARNING] No match found for {row['title']}")

            with open(args.output_csv, 'a', newline='', encoding='utf-8') as outfile:
                writer = csv.DictWriter(outfile, fieldnames=fieldnames)
                writer.writerow(output_row)
                print(f"[WRITTEN] Updated record for {row['title']}")

            processed_ids.add(row['imdb_id'])
            time.sleep(1.5)

    write_channels_csv(channels_csv, channel_cache)

def process_json(args):
    output_json = os.path.splitext(args.output_csv)[0] + '.json'
    df = pd.read_csv(args.output_csv)
    
    # Clean data
    df['year_of_release'] = pd.to_numeric(df['year_of_release'], errors='coerce')
    df = df[df['year_of_release'].between(1900, 2025)]
    
    df['runtime'] = pd.to_numeric(df['runtime'], errors='coerce').replace(-1, pd.NA)
    
    # Handle string columns safely
    df['imdb_votes'] = df['imdb_votes'].astype(str).str.replace(',', '').replace('nan', '0').astype(int)
    df['genres'] = df['genres'].fillna('').apply(lambda x: x.split('|') if x else [])
    df['directors'] = df['directors'].fillna('').apply(lambda x: x.split('|') if x else [])
    df['writers'] = df['writers'].fillna('').apply(lambda x: x.split('|') if x else [])
    
    df['imdb_rating'] = pd.to_numeric(df['imdb_rating'], errors='coerce')
    df['has_wins_nominations'] = df['wins_nominations'].notna() & (df['wins_nominations'] != '')
    
    # Calculate movie era
    def get_movie_era(year):
        if pd.isna(year):
            return 'Unknown'
        if year <= 1980:
            return 'Classic'
        elif 1981 <= year <= 2000:
            return 'Golden'
        elif 2001 <= year <= 2020:
            return 'Modern'
        else:
            return 'Contemporary'
    df['movie_era'] = df['year_of_release'].apply(get_movie_era)
    
    # Calculate IMDb relevance
    min_votes = df['imdb_votes'].min()
    max_votes = df['imdb_votes'].max()
    df['normalized_votes'] = (df['imdb_votes'] - min_votes) / (max_votes - min_votes) if max_votes != min_votes else 0.0
    df['imdb_relevance'] = (df['imdb_rating'] / 10 * 0.6) + (df['normalized_votes'] * 0.3) + (df['has_wins_nominations'] * 0.1)
    
    # Convert to JSON
    df.to_json(output_json, orient='records', indent=2)
    print(f"[JSON] Successfully wrote {len(df)} records to {output_json}")

def main():
    args = parse_args()
    process_csv(args)
    process_json(args)

if __name__ == '__main__':
    main()

