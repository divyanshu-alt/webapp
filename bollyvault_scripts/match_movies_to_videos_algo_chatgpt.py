#!/usr/bin/env python3
import argparse
import pandas as pd
import re
import csv
import os
import sys

def parse_args():
    p = argparse.ArgumentParser(
        description="Match YouTube video links to Bollywood movies by title + year"
    )
    p.add_argument('--main_csv',      required=True, help="CSV with columns: title,year_of_release")
    p.add_argument('--video_csv',     required=True, help="CSV with columns: url,normalized_translated_title_n_desc,year_optional,...")
    p.add_argument('--output_csv',    required=True, help="Where to write the matching results")
    p.add_argument('--other_closer_count', type=int, default=2,
                   help="How many other_closer links to output per movie (default=2)")
    return p.parse_args()

def load_data(main_path, video_path):
    movies = pd.read_csv(main_path, dtype={'title': str, 'year_of_release': int})
    videos = pd.read_csv(video_path, dtype={'url': str,
                                            'normalized_translated_title_n_desc': str,
                                            'year_optional': str})
    # lowercase for matching
    movies['title_lower'] = movies['title'].str.lower()
    videos['norm_desc_lower'] = videos['normalized_translated_title_n_desc'].str.lower().fillna('')
    # parse year_optional or NaN
    videos['year_optional'] = pd.to_numeric(videos['year_optional'], errors='coerce')
    return movies, videos

def compile_pattern(title):
    # \b ensures standalone words/spaces; escape special chars
    return re.compile(r'\b' + re.escape(title) + r'\b')

def score_match(title, vid_year, movie_year):
    word_count = len(title.split())
    year_bonus = 1 if (not pd.isna(vid_year) and int(vid_year) == int(movie_year)) else 0
    return word_count + year_bonus, bool(year_bonus)

def main():
    args = parse_args()
    movies, videos = load_data(args.main_csv, args.video_csv)

    # sort movies so longest titles go first (to enforce longest-match priority)
    movies['title_len'] = movies['title_lower'].str.split().str.len()
    movies = movies.sort_values(by='title_len', ascending=False)

    best_assigned = set()
    # prepare output file & header
    other_n = args.other_closer_count
    headers = ['movie_title','year_of_release','best_url','best_score','best_year_matches']
    for i in range(1, other_n+1):
        headers += [f'other_closer_url{i}', f'other_closer_score{i}', f'other_closer_year_matches{i}']

    with open(args.output_csv, 'w', newline='', encoding='utf-8') as out_f:
        writer = csv.DictWriter(out_f, fieldnames=headers)
        writer.writeheader()

        # process each movie
        for _, m in movies.iterrows():
            title = m['title_lower']
            year  = m['year_of_release']
            pat   = compile_pattern(title)
            print(f"[DEBUG] Processing movie: '{m['title']}' ({year})", file=sys.stderr)

            # find all candidate videos that contain this exact title
            candidates = []
            for _, v in videos.iterrows():
                text = v['norm_desc_lower']
                if pat.search(text):
                    sc, ym = score_match(title, v['year_optional'], year)
                    candidates.append({'url': v['url'], 'score': sc, 'year_match': ym})

            # pick best non-assigned candidate
            best = None
            for c in sorted(candidates, key=lambda x: (-x['score'], x['url'])):
                if c['url'] not in best_assigned:
                    best = c
                    break

            if best:
                best_assigned.add(best['url'])
                print(f"[DEBUG]  → Best: {best['url']} (score={best['score']}, year_match={best['year_match']})",
                      file=sys.stderr)
                best_url, best_score, best_year = best['url'], best['score'], best['year_match']
            else:
                print("[DEBUG]  → No best match found", file=sys.stderr)
                best_url = best_score = ''
                best_year = False

            # pick N other closer from all candidates (including those used as best elsewhere)
            others = [c for c in sorted(candidates, key=lambda x: -x['score']) if c['url'] != best_url]
            others = others[:other_n]

            # build output row
            row = {
                'movie_title': m['title'],
                'year_of_release': year,
                'best_url': best_url,
                'best_score': best_score,
                'best_year_matches': best_year
            }
            for idx in range(other_n):
                key_url    = f'other_closer_url{idx+1}'
                key_score  = f'other_closer_score{idx+1}'
                key_ym     = f'other_closer_year_matches{idx+1}'
                if idx < len(others):
                    row[key_url]   = others[idx]['url']
                    row[key_score] = others[idx]['score']
                    row[key_ym]    = others[idx]['year_match']
                    print(f"[DEBUG]  → Other {idx+1}: {others[idx]['url']} (score={others[idx]['score']}, year_match={others[idx]['year_match']})",
                          file=sys.stderr)
                else:
                    row[key_url] = row[key_score] = row[key_ym] = ''

            writer.writerow(row)
            out_f.flush()
            os.fsync(out_f.fileno())

        print(f"[DEBUG] All done. Results in: {args.output_csv}", file=sys.stderr)

if __name__ == '__main__':
    main()

