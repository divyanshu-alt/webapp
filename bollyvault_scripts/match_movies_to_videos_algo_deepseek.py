import csv
import re
import argparse
from collections import defaultdict

def read_movies(filename):
    movies = []
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row['title'].strip().lower()
            year = int(row['year_of_release'])
            movies.append({'title': title, 'year': year})
    movies.sort(key=lambda x: -len(x['title']))
    return movies

def read_video_links(filename):
    videos = []
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized_title = row['normalized_translated_title_n_desc'].strip().lower()
            year_optional = row['year_optional'].strip()
            year = int(year_optional) if year_optional.isdigit() else None
            videos.append({
                'url': row['url'],
                'normalized_title': normalized_title,
                'year': year,
                'translated_title': row['translated_title_n_desc']
            })
    return videos

def find_best_matches(movies, videos):
    best_matches = {}
    used_video_indices = set()

    for movie_idx, movie in enumerate(movies):
        print(f"Processing movie {movie_idx + 1}/{len(movies)}: {movie['title']} ({movie['year']})")
        best_score = -1
        best_video_idx = None
        best_year_match = False

        for video_idx, video in enumerate(videos):
            if video_idx in used_video_indices:
                continue

            pattern = r'\b{}\b'.format(re.escape(movie['title']))
            if re.search(pattern, video['normalized_title']):
                score = len(movie['title'])
                year_match = False

                if video['year'] is not None and video['year'] == movie['year']:
                    score += 1000
                    year_match = True

                if score > best_score:
                    best_score = score
                    best_video_idx = video_idx
                    best_year_match = year_match

        if best_video_idx is not None:
            print(f"Found best match: {videos[best_video_idx]['url']} with score {best_score}, year match {best_year_match}")
            used_video_indices.add(best_video_idx)
            best_matches[movie_idx] = {
                'video_idx': best_video_idx,
                'score': best_score,
                'year_match': best_year_match
            }
        else:
            print("No best match found.")
            best_matches[movie_idx] = None

    return best_matches, used_video_indices

def find_other_closer_matches(movies, videos, used_video_indices, num_other):
    other_matches = defaultdict(list)

    for movie_idx, movie in enumerate(movies):
        print(f"Finding other matches for movie {movie_idx + 1}/{len(movies)}: {movie['title']}")
        candidates = []

        for video_idx, video in enumerate(videos):
            if video_idx in used_video_indices:
                continue

            pattern = r'\b{}\b'.format(re.escape(movie['title']))
            if re.search(pattern, video['normalized_title']):
                score = len(movie['title'])
                year_match = False

                if video['year'] is not None and video['year'] == movie['year']:
                    score += 1000
                    year_match = True

                candidates.append((video_idx, score, year_match))

        candidates.sort(key=lambda x: (-x[1], -x[0]))
        other_matches[movie_idx] = candidates[:num_other]

        print(f"Found {len(other_matches[movie_idx])} other matches")

    return other_matches

def write_output(movies, videos, best_matches, other_matches, output_file, num_other):
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        headers = ['movie_title', 'year_of_release', 'best_url', 'best_score', 'best_year_matches']
        for i in range(num_other):
            headers.extend([
                f'other_closer_url{i+1}',
                f'other_closer_score{i+1}',
                f'other_closer_year_matches{i+1}'
            ])
        writer.writerow(headers)

        for movie_idx, movie in enumerate(movies):
            row = [movie['title'], movie['year']]
            best_info = best_matches[movie_idx]

            if best_info:
                video = videos[best_info['video_idx']]
                row.extend([
                    video['url'],
                    best_info['score'],
                    best_info['year_match']
                ])
            else:
                row.extend(['', '', ''])

            others = other_matches.get(movie_idx, [])
            for i in range(num_other):
                if i < len(others):
                    vid_idx, score, year_match = others[i]
                    video = videos[vid_idx]
                    row.extend([video['url'], score, year_match])
                else:
                    row.extend(['', '', ''])

            writer.writerow(row)
            f.flush()

def main():
    parser = argparse.ArgumentParser(description='Match video links to movies.')
    parser.add_argument('--main', required=True, help='Main CSV file')
    parser.add_argument('--video-links', required=True, help='Video links CSV file')
    parser.add_argument('--output', required=True, help='Output CSV file')
    parser.add_argument('--num-other', type=int, default=2, help='Number of other close matches')
    args = parser.parse_args()

    print("Reading movies...")
    movies = read_movies(args.main)
    print(f"Loaded {len(movies)} movies")

    print("Reading video links...")
    videos = read_video_links(args.video_links)
    print(f"Loaded {len(videos)} video links")

    print("Matching best videos...")
    best_matches, used_videos = find_best_matches(movies, videos)

    print("Matching other close videos...")
    other_matches = find_other_closer_matches(movies, videos, used_videos, args.num_other)

    print("Writing output...")
    write_output(movies, videos, best_matches, other_matches, args.output, args.num_other)

    print("Completed successfully")

if __name__ == '__main__':
    main()

