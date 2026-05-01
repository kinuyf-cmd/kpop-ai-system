"""X投稿管理 — 記事draft化時のツイート自動削除"""
import json, os, sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system/google_metrics')

def delete_tweet(tweet_id):
    """X API v2 でツイート削除"""
    try:
        from dotenv import load_dotenv
        load_dotenv('/home/aiuser/kpop-ai-system/.env')
        import pathlib
        import post_to_x
        post_to_x.RETRY_LOG = pathlib.Path('/home/aiuser/kpop-ai-system/logs/x_retry_log_v2.jsonl')
        
        creds, errors = post_to_x.validate_credentials()
        if errors:
            return {'success': False, 'error': str(errors)}
        
        import requests
        from requests_oauthlib import OAuth1
        oauth = OAuth1(creds['api_key'], creds['api_secret'],
                       creds['access_token'], creds['access_token_secret'])
        r = requests.delete(f'https://api.twitter.com/2/tweets/{tweet_id}', auth=oauth, timeout=10)
        
        if r.status_code == 200:
            return {'success': True, 'deleted': True}
        elif r.status_code == 404:
            return {'success': True, 'deleted': False, 'reason': 'already_deleted'}
        else:
            return {'success': False, 'status': r.status_code, 'error': r.text[:200]}
    except Exception as e:
        return {'success': False, 'error': str(e)[:200]}


def find_tweets_for_post(post_id):
    """x_posts.jsonl から特定記事のtweet_idを検索"""
    log_path = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
    tweet_ids = []
    if not os.path.exists(log_path):
        return tweet_ids
    for line in open(log_path):
        try:
            e = json.loads(line)
            # post_id一致 or URL内にpost_id
            if (str(post_id) in str(e.get('url', '')) or 
                str(post_id) in str(e.get('text', ''))):
                tid = e.get('tweet_id')
                if tid:
                    tweet_ids.append(tid)
        except:
            pass
    return tweet_ids


def delete_tweets_for_post(post_id):
    """記事に紐づく全ツイートを削除"""
    tweet_ids = find_tweets_for_post(post_id)
    results = []
    for tid in tweet_ids:
        r = delete_tweet(tid)
        results.append({'tweet_id': tid, **r})
    return results
