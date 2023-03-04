import inquirer
import requests
from bs4 import BeautifulSoup
import mysql.connector
import aiohttp
import asyncio
import async_timeout
import urllib.parse
import config
import sys

#function for prompting user to define search engine and query
def get_inputs():
    #define search engine options for inqurer 
    engine_options = [inquirer.List('Search Engine',
                message="Choose Search Engine:",
                choices=list(config.engines.keys()),),]
    #prompt user to select search engine 
    engine = inquirer.prompt(engine_options)['Search Engine']
    #prompt user to input web search query
    input_query = input('Enter search query: ')
    
    return engine, input_query 

#special logic for javascript handling in DuckDuckGo
def get_js_soup(url):
    #import selenium only for search engines that load urls via javascript
    import selenium
    from selenium import webdriver
    try: 
        #define browser using safari driver 
        browser = webdriver.Safari()
        #request url
        browser.get(url)
        #get html from webpage
        soup = BeautifulSoup(browser.page_source, 'html.parser')
        #quit browser 
        browser.quit()
        return soup
    except selenium.common.exceptions.WebDriverException:
        print('\nWebdriver Exception. Search engine option capatible with Safari only.\n')
        sys.exit(1) 

#filter function to clean up url scrape results 
def filter_function(url,block_list,ad_block_list):
    #check for http
    if 'http' not in url: 
        return False
    #check if included in config.block_list and config.ad_block_list
    elif any(blocked in url for blocked in block_list) or any(blocked in url for blocked in ad_block_list):
        return False
    else:
        return True
    
#additional data transformations for google searches 
def google_transformer(url):
    return url.split('&sa=')[0]

#function for finding urls resulted from search, with associated html clean up and filtering 
#return list of cleaned up url 
def urls(soup,engine):
    #find <a> tages used for links, where tags have href attribute from soup object
    all_href = map(lambda x: x.get('href'),soup.find_all('a',href=True))
    #filter to url links 
    url = filter(lambda x: filter_function(x,config.block_list,config.ad_block_list), all_href)
    #additional filter for google searches
    if engine=='Google':
        url = map(google_transformer,url)
    #return cleaned up list of urls 
    return list(map(str,map(lambda x: x.strip('/url?q='),url)))

#remove duplicate domains from scraped urls
def remove_dup(urls):
    #dictionary to hold domain key and url value 
    new_urls={}
    #for each url, check if domain is in dictionary 
    for url in urls:
        parts = urllib.parse.urlparse(url)
        if parts.netloc not in new_urls:
            #add domain and url into dictionary 
            new_urls[parts.netloc] = url
    #return filtered urls as a list 
    return list(new_urls.values())

#get raw text from html resulting from engine scrape
def get_raw_text(text):
    soup = BeautifulSoup(text,'html.parser')
    for script in soup(['script','style','template','TemplateString','ProcessingInstruction','Declaration','Doctype']):
        script.extract()
    return (soup.get_text(strip=True).replace(u'\xa0', u' ').encode('ascii','ignore'))

#async get html from url 
async def get_html(session, url):
    #get html text from session object 
    try:
        async with async_timeout.timeout(10):
            async with session.get(url) as response:
                return await response.text(), url
    #if timeout, return "TimeoutError" and url as tuple 
    except asyncio.exceptions.TimeoutError:
        return "Error: Timeout", url
    #if invalid url, return "InvalidURL" and url as tuple 
    except aiohttp.client_exceptions.InvalidURL:
        return "Error: InvaidURL", url 
    #if server disconnected, return "ServerDisconnected" and url as tuple
    except aiohttp.client_exceptions.ServerDisconnectedError:
        return 'Error: ServerDisconnected', url 
    except UnicodeDecodeError:
        return 'Error: UnicodeDecodeError', url
    
#define tasks for the urls 
async def get_all(session, urls):
    tasks = []
    #for each url, create a task to get html for the defined session object and url 
    for url in urls:
        task = asyncio.create_task(get_html(session, url))
        tasks.append(task)
    #return all the tasks 
    results = await asyncio.gather(*tasks)
    return results 

#define function to call async functions 
async def async_main(urls):
    #context manager for aiohttp session object 
    async with aiohttp.ClientSession() as session:
        #get data obtained from get_all with defined session object and urls 
        data = await get_all(session, urls)
        #return list of data, where each element is a tuple containing html, url 
        return data

#function for executing sql queries
def sql_execute(cursor, query, input, get_lastrowid = False):
    cursor.execute(query, input)
    if (get_lastrowid): 
        return cursor.lastrowid


def main():
    #get engine and query from user 
    engine, input_query = get_inputs()

    if engine not in config.js_engines:
        #request html from web search
        r = requests.get(config.engines[engine]+input_query, headers={'user-agent': 'my-app/0.0.1'})
        #create beautifulsoup object 
        soup = BeautifulSoup(r.text, 'html.parser')
    else:
        #use special handling for javascript 
        soup = get_js_soup(config.engines[engine]+input_query)

    #get scraped urls, while removing duplicate domains 
    url_list = remove_dup(urls(soup,engine))

    #asynchronously get html text from urls obtained via search engine scrape
    text_url = asyncio.run(async_main(url_list))

    #return cleaned up text as a tuple with the url
    cleaned_text_url = map(lambda x: (get_raw_text(x[0]),x[1]), text_url)

    #get config MySQL parameters
    mySQLparams = config.mySQLparams
    #opening connection to MySQL database
    connection = mysql.connector.connect(user=mySQLparams['user'], database = mySQLparams['database'], password = mySQLparams['password'])
    #creating cursor handler for inserting data 
    cursor = connection.cursor()

    #query for adding search info
    last_search_id = sql_execute(cursor,config.add_search,(input_query,engine),get_lastrowid=True)

    #get config variables to use in for loop
    add_engine_info = config.get_add_engineinfo(config.tables[engine])

    #inserting url info
    for text,url in cleaned_text_url:
        #restricting size of text for database constraint
        if len(text) > 60000:
            text = text[:60000]
        #execute query to add info to search engine tables
        sql_execute(cursor,add_engine_info,(url,last_search_id,text))
        
    #commit data to database 
    connection.commit()

    #closing cursor and connection 
    cursor.close()
    connection.close()

if __name__ == '__main__':
    main()