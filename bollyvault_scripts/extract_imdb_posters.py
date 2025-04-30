import requests
from bs4 import BeautifulSoup
import re
import time

def extract_imdb_id(url):
    match = re.search(r'/title/(tt\d+)', url)
    return match.group(1) if match else None

def get_modified_poster_url(imdb_url, width=500):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(imdb_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        meta_tag = soup.find('meta', property='og:image')
        if meta_tag and meta_tag.get('content'):
            original_url = meta_tag['content']
            # Modify the URL to request the desired width
            modified_url = re.sub(r'\._V1_.*?(\.jpg)$', f'._V1_UX384_.jpg', original_url)
            return modified_url
        else:
            print(f"No og:image found for {imdb_url}")
            return None
    except Exception as e:
        print(f"Error processing {imdb_url}: {e}")
        return None

def main():
    input_file = 'imdb_links.txt'
    output_file = 'imdb_posters_500px.txt'

    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', encoding='utf-8') as outfile:
        for line in infile:
            imdb_url = line.strip()
            if not imdb_url:
                continue
            print(f"Processing: {imdb_url}")
            poster_url = get_modified_poster_url(imdb_url, width=500)
            if poster_url:
                outfile.write(f"{imdb_url}\t{poster_url}\n")
            else:
                outfile.write(f"{imdb_url}\tNo poster found\n")
            time.sleep(1)  # Be polite and avoid overwhelming the server

if __name__ == "__main__":
    main()

