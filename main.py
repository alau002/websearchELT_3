import inquirer
import requests
from bs4 import BeautifulSoup
import mysql.connector
import aiohttp
import asyncio
import config

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

#get raw text from urls resulting from engine scrape
def get_raw_text(url):
    soup = BeautifulSoup(requests.get(url).text,'html.parser')
    for script in soup(['script','style','template','TemplateString','ProcessingInstruction','Declaration','Doctype']):
        script.extract()
    return (url,soup.get_text(strip=True).replace(u'\xa0', u' ').encode('ascii','ignore')[0:1000])

#async get html from url 
async def get_html(session, url):
    #get html text from session object 
    async with session.get(url) as response:
        return await response.text()
    
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
        #return list of data 
        return data 


def main():
    #get engine and query from user 
    engine, input_query = get_inputs()

    #request html from web search
    r = requests.get(config.engines[engine]+input_query, headers={'user-agent': 'my-app/0.0.1'})

    #create beautifulsoup object 
    soup = BeautifulSoup(r.text, 'html.parser')

    #get url and raw text from scraped urls
    url_text = map(lambda x: get_raw_text(x), urls(soup,engine))

    #get config MySQL parameters
    mySQLparams = config.mySQLparams
    #opening connection to MySQL database
    connection = mysql.connector.connect(user=mySQLparams['user'], database = mySQLparams['database'], password = mySQLparams['password'])
    #creating cursor handler for inserting data 
    cursor = connection.cursor()

    #query for adding search info
    add_search = ('INSERT INTO searches(query,engine) values(%(query)s, %(engine)s)')

    #inserting search info 
    cursor.execute(add_search,{'query':input_query, 'engine':engine})
    #obtain last row id of the search table to insert into foreign keys
    last_search_id = cursor.lastrowid

    #inserting url info
    for url,text in url_text:
        tables = config.tables
        query = 'INSERT INTO ' +tables[engine]+'(url,search_id,raw_text) values(%s,%s,%s)'
        cursor.execute(query, (url,last_search_id,text))
        
    #commit data to database 
    connection.commit()

    #closing cursor and connection 
    cursor.close()
    connection.close()

if __name__ == '__main__':
    main()