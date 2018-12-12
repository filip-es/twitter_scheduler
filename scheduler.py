#!/usr/local/bin/python3

import json
import time
import calendar
import sys

from urllib.parse import quote_plus
from random import randint, shuffle
from datetime import datetime
from collections import namedtuple

import requests
from bs4 import BeautifulSoup as bs

FILEPATH = sys.path[0]

with open(f'{FILEPATH}/config.json') as f:
    config = json.load(f)


Article = namedtuple("Article", ["title", "url", "engagement", "published"])
CArticle = namedtuple("CArticle", ["title", "url"])


def make_request(url, method, headers={}, params={}, payload={}) -> json:
    """Convenience function for making requests

    Returns
    -------
    json dict
    """
    assert method in ['get', 'post']

    if method == 'get':
        response = requests.get(url, headers=headers, params=params)
    elif method == 'post':
        assert payload
        response = requests.post(url, headers=headers, params=params, data=payload)

    return response.json()



def get_feed(time_delta=1, count=100, **kwargs) -> list:
    """Get data from Feedly stream specified in config.json
    Result articles are sorted from most to least popular based on engagement number.
    For **kwargs see API Docs: https://developer.feedly.com/v3/streams/

    Parameters
    ---------
    time_delta : int
        number of days in the past to return articles from. E.g. 1 means return articles
        from last 24hrs (default is 1)
    count : int
        number of articles to be returned (default is 100, min=20, max=10000)

    Returns
    -------
    list of `Article` objects
    """

    # Load config
    feedly = config['feedly']
    url = feedly['baseurl']
    token = feedly['token']
    stream = feedly['streams']['twitter']

    url += f"/streams/{quote_plus(stream)}/contents"
    headers = {"Authorization": f"OAuth {token}"}

    response = make_request(url, 'get', headers=headers, params=kwargs)
    
    # error handling
    if not response.get('items'):
        if response.get('errorCode'):
            print("ERROR getting feedly content!\n" \
                 f"Message: {response.get('errorMessage')}\n" \
                 f"Code:    {response.get('errorCode')}")
            sys.exit(1)

        print(f"ERROR getting feedly content!\nMessage:\t{response}")
        sys.exit(1)

    data = response.get('items')
    
    articles = []
    now = datetime.utcnow()
    for i in data:
        published = i.get('published')
        if not published:
            continue
       
        delta = now - datetime.utcfromtimestamp(published / 1000)
        if delta.days == time_delta:
            break
        title, url, engagement = i.get('title'), i.get('originId'), i.get('engagement', 0)

        article = Article._make([title, url, engagement, published])
        articles.append(article)

    articles.sort(key=lambda f: f.engagement, reverse=True) # sort by engagement descending

    return articles
    #return response


def get_clicky(date='today', output='json', limit=50, **kwargs) -> list:
    """Get all 'news' URLs from website connected to Clicky.com
    For **kwargs see API Docs: https://clicky.com/help/api
    
    Parameters
    ----------
    date : str
        when to retrieve articles from. e.g. today, yesterday, X-days-ago, YYYY-MM-DD (default is today)
    output : str
        respose format => xml, php, json, csv (default is json)
    limit : int
        number of retrieved articles
    
    Returns
    -------
    list of `CArticle` objects
    """
    
    # Load config
    clicky = config['clicky']

    sid = clicky['siteid']
    skey = clicky['sitekey']
    url = clicky['urls']['api_url']


    params = {
        "site_id": sid,
        "sitekey": skey,
        "type": "pages",
        "output": output,
        "date": date,
        "limit": limit
    }

    params.update(kwargs)

    response = make_request(url, 'get', params=params)

    articles = []
    for i in response[0]['dates'][0]['items']:
        url = i['url'].split('/')
        if url[3] == 'news' and len(url) > 4:
            articles.append(CArticle._make([i['title'], i['url']]))

    return articles
    # return response


# Scrape the urls instead of using API
# NOT USED
def scrape_clicky(date='yesterday') -> list:
    # Load config
    clicky = config['clicky']

    login_url = clicky['urls']['login_url']
    content_url = clicky['urls']['content_url']

    username = clicky['username']
    pw = clicky['pw']

    # Initiate session (for cookie persistance)
    session = requests.session()

    # Login
    payload = {"username": username, "password": pw}
    login = session.post(login_url, data=payload)

    # Get content
    params = {"site_id": clicky['siteid'], "date": date}
    content = session.get(content_url, params=params)

    session.close()

    # Parse HTML to get urls from table
    soup = bs(content.text, 'lxml')
    rows = soup.find('table', class_= "graph").find_all('tr', class_= 'alt')
    urls = []

    for i in rows:
        url = i.find('td', class_="itemname2").find_all('a')[1].text
        if url.startswith("/news/"):
            urls.append(url)

    return urls



def schedule_buffer(status_text, profile, scheduled=0, **kwargs) -> json:
    """Schedules posts to buffer connected social media.
    (So far only twitter is implemented)

    Paramenters
    ----------
    status_text : str
        content of post (use text + url)
    profile : str
        which social media to post to (must be 'twitter')
    scheduled : int
        time to scheudle to post (must be timestamp)
        
    Returns
    -------
    json of `requests.Response`
    """
    # Load config
    buffer = config['buffer']

    if isinstance(profile, str):
        assert profile in ['twitter', 'linkedin']
        profile_id = buffer['profiles'][profile]
    if isinstance(profile, list):
        raise NotImplementedError()
        for i in profile:
            assert i in ['twitter', 'linkedin']
            # TODO: implement multiple streams


    url = buffer['baseurl'] + 'updates/create.json'
    access_token = buffer['access_token']

    params = {"access_token": access_token}
    params.update(kwargs)


    payload = {
        "profile_ids": profile_id,
        "text": status_text
        }

    if not scheduled:
        payload.update({"now": True})
    else:
        if isinstance(scheduled, str):
            raise NotImplementedError("Please use a timestamp")
        if isinstance(scheduled, int):
            assert len(str(scheduled)) == 10 # make sure seconds

        payload.update({"scheduled_at": scheduled})

    response = make_request(url, 'post', params=params, payload=payload)
    return response



def _get_buffer_profiles() -> json:
    """Prints IDs of buffer profiles"""

    # Load config
    buffer = config['buffer']
    url = buffer['baseurl'] + 'profiles.json'
    access_token = buffer["access_token"]

    params = {"access_token": access_token}

    response = make_request(url, 'get', params=params)

    for i in response:
        print(f"{i['service']}\t{i['_id']}")

    # return response



def get_posting_times() -> list:
    """Checks posting hours specified in config file and gets random time during that hour.
    e.g. posting hour is 13 => returns timestamp of 13:random.randint(1,59)
    Skips hours in the past. (all times calculated in UTC)

    Returns
    -------
    list of UTC timestamps
    """

    posting_hrs = config['posting_hours']
    timestamps = []

    # Determine current UTC time
    today = datetime.utcnow()
    y, m, d, h = today.year, today.month, today.day, today.hour

    # Skip hours in the past
    # Calculate UTC timestamps
    for index, hour in enumerate(posting_hrs):
        if h > hour:
            continue
        if h == hour:
            hour += 1

        # generate random time within one hour of posting time range
        posting_time = datetime(y, m, d, hour, randint(1,59), randint(1,59))
        timestamps.append(calendar.timegm(posting_time.timetuple()))


    return timestamps


def check_posted(source, count, posted) -> list:
    """Check if URL was already posted. If yes, use the next in line.

    Parametes
    --------
    source : list of `Article` or `CArticle` objects
        returned from appropriate get functions (get_feed() and get_clicky())
    count : int
        number of articles to be posted (specified in config file
    posted : list of URLs
        list of URLs that have been previously posted. (check source articles against this list)
    
    Returns
    -------
    list of `Article` objects
    """

    articles = []
    added = 0
    for i in source:
        if added == count:
            break
        if i.url in posted:
            continue
        articles.append(i)
        added += 1

    return articles



def main():
    args = sys.argv
    if len(args) == 2:
        if args[1] == "streams":
            _get_buffer_profiles()
            sys.exit(0)
        else:
            print(f"Invalid argument!\t\"{args[1]}\"\nExiting...")
            sys.exit(1)

    utc_today = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"UTC Time now:\t{utc_today}\n")

    # Check if done today
    with open(f"{FILEPATH}/done_today.txt") as f:
        last = f.read().strip()

    if last == utc_today.split(' ')[0]:
        print("Already scheduled today!\nExiting...")
        sys.exit(0)

    # Load number of articles to post from each source
    articles = config['articles']
    feedly_count = articles['feedly']
    clicky_count = articles['clicky']

    # Make sure number of posting hours matches number of articles to post
    assert len(config['posting_hours']) == sum(articles.values())

    # Get lists of URLS from APIs
    feedly = get_feed()
    clicky = get_clicky()

    # Check if posted before and select URLs
    with open(f"{FILEPATH}/posted.txt") as f:
        posted = [i.strip() for i in f.readlines()]

    feedly_urls = check_posted(feedly, feedly_count, posted)
    clicky_urls = check_posted(clicky, clicky_count, posted)

    # Get posting times and urls
    posting_times = get_posting_times()
    to_schedule = feedly_urls + clicky_urls

    # Randomize order
    shuffle(to_schedule)

    # Schedule posts
    for index, i in enumerate(posting_times):
        title = to_schedule[index].title
        url = to_schedule[index].url
        schedule_time = datetime.utcfromtimestamp(i).strftime('%Y-%m-%d %H:%M:%S')

        print(f"\nScheduling...\nURL:\t{url}\nTime:\t{schedule_time}")

        tweet = schedule_buffer(f"{title} {url}", 'twitter', scheduled=i)

        if tweet['success']:
            print("Scheduled successfully!")
            posted.append(url)
        else:
            print(f"Something went wrong scheduling {url}")
            print(f"ERROR:\t{tweet['message']}")
            print(tweet)

        time.sleep(1)

    # Update posted articles
    with open(f"{FILEPATH}/posted.txt", 'w') as f:
        for i in posted:
            f.write(f"{i}\n")

    # Update today check
    with open(f"{FILEPATH}/done_today.txt", 'w') as f:
        f.write(utc_today.split(' ')[0])




if __name__ == "__main__":
    main()
