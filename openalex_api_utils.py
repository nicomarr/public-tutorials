import os
from pathlib import Path
import re
import json
import time
from datetime import datetime, timedelta
import requests
from typing import Dict, Any, List, Optional
from tqdm import tqdm


def get_works(ids: list, email: str, pdf_output_dir: str = None, persist_dir: str = None, entry_type: str = "primary entry", enable_selenium: bool = False, is_headless: bool = True, show_progress: bool = False, verbose: bool = False) -> tuple[list, list]:
    """
    Get information about works from OpenAlex API. Works are scholarly documents like journal articles, books, datasets, and theses.
    
    Args:
        ids (list): List of IDs of works to get information about. Accepts Pubmed IDs (PMID), PubMed Central ID (PMCID), DOI, and OpenAlex IDs.
        email (str): Email address to use in the API request.
        pdf_output_dir (str, optional): Directory to save the PDFs if available. Defaults to None.
        persist_dir (str, optional): Directory to save the JSON response for each work. Defaults to None.
        entry_type (str, optional): Type of entry to retrieve. Options are 'primary entry', 'reference of primary entry', 'citing primary entry', and 'related to primary entry'. Defaults to 'primary entry'.
        enable_selenium (bool, optional): If True, enables the use of Selenium for downloading PDFs. Defaults to False. Install the Chrome browser and the Chrome WebDriver to use this option.
            Note: Enabling Selenium can add a delay.
            This option is only used for open access works that cannot be downloaded using the requests library. 
        is_headless (bool, optional): If True, runs the browser in headless mode (i.e, without any visible UI). Defaults to True.
        show_progress (bool, optional): If True, displays a progress bar. Defaults to False.
        verbose (bool, optional): If True, prints detailed status messages. Defaults to False. Disabled if show_progress is True.
        
    Returns:
        tuple: A tuple containing two lists:
            - works (list): List of dictionaries containing information about the works.
            - failed_calls (list): List of dictionaries containing information about failed API calls.
            
    Note:
        To use Selenium options, install the Chrome browser and the Chrome WebDriver.
    """

    
    # Input validation
    assert email, "Please provide your Email to use OpenAlex API."
    assert ids, "Please provide a list of IDs to retrieve data."
    assert isinstance(ids, list), "IDs must be provided as a list."
    assert entry_type in ["primary entry", "reference of primary entry", "citing primary entry", "related to primary entry"], "Invalid entry_type. Options are 'primary entry', 'reference of primary entry', 'citing primary entry', and 'related to primary entry'."
    assert verbose in [True, False], "Verbose must be a boolean value."
    assert isinstance(pdf_output_dir, str) or pdf_output_dir is None, "pdf_output_dir must be a string or None."
    assert isinstance(persist_dir, str) or persist_dir is None, "persist_dir must be a string or None."
    
    if pdf_output_dir:
        warning_message = "WARNING: Downloading PDFs may be subject to copyright restrictions. Ensure you have the right to download and use the content."
        print(warning_message)

    # Initialize variables used for the API request and function
    base_url = "https://api.openalex.org/works/"
    params = {
        "mailto": email,
        "select": "id,doi,title,authorships,publication_year,publication_date,ids,language,primary_location,type,open_access,has_fulltext,cited_by_count,cited_by_percentile_year,biblio,primary_topic,topics,keywords,concepts,mesh,best_oa_location,sustainable_development_goals,referenced_works,related_works,ngrams_url,cited_by_api_url,counts_by_year,updated_date,created_date", # Add or remove fields as needed 
    }
    # select option in params allows root-level fields to be specified. The following root-level fields are available:
        # id
        # doi
        # title
        # authorships
        # publication_year
        # publication_date
        # ids
        # language
        # primary_location
        # type
        # type_crossref
        # open_access
        # has_fulltext
        # cited_by_count
        # cited_by_percentile_year
        # biblio
        # primary_topic
        # topics
        # keywords
        # concepts
        # mesh
        # best_oa_location
        # sustainable_development_goals
        # referenced_works
        # related_works
        # ngrams_url
        # cited_by_api_url
        # counts_by_year
        # updated_date
        # created_date
        # see https://docs.openalex.org/api-entities/works/filter-works for more details
    works = []
    failed_calls = []
    doi_regex = r"10.\d{1,9}/[-._;()/:A-Za-z0-9]+" # Regular expression to match DOIs
    todays_date = datetime.now().date()
    now = datetime.now() # Get the current date and time.
    iter_count = 0

    # Display a progress bar if show_progress is True
    if show_progress:
        iterable = tqdm(ids, desc="Retrieving works") # Wrap the list of IDs with tqdm to display a progress bar.
        verbose = False # Disable verbose mode if show_progress is True.
    else:
        iterable = ids

    # Iterate over each ID in the list to retrieve information about the works.
    for id in iterable:
        # Initialize variables used for each iteration
        response = None
        data = None
        url = None
        pdf_url = None
        pdf_path = None
        status_message = ""
        persist_datetime = None
        
        # Remove the prefix from the ID if it is a URL.
        if id.startswith("https://openalex.org/") or id.startswith("https://api.openalex.org/"):
            id = id.split("/")[-1]
        if id.startswith("https://doi.org/"):
            id = id.replace("https://doi.org/", "")
        
        # Print the ID for the current iteration if verbose is True.
        if verbose: print("---")

        # If a persist_dir is provided, check if a JSON file already exists for the work. If so, load the data from the file if it is not older than 30 days.
        if persist_dir:
            was_resently_persisted = False # Initialize a flag to check if the data was recently persisted.
            works_from_storage = load_works_from_storage(persist_dir) # Load the JSON files for works from the specified directory.
            for _work in works_from_storage:
                _uid = _work["uid"]
                _doi = _work["metadata"]["ids"]["doi"] if "doi" in _work["metadata"]["ids"] else None
                _pmid = _work["metadata"]["ids"]["pmid"] if "pmid" in _work["metadata"]["ids"] else None
                if id == _uid or id == _doi or id == _pmid:
                    persist_datetime = _work["persist_datetime"]
                    if (todays_date - datetime.strptime(persist_datetime, "%Y-%m-%dT%H:%M:%S.%f").date()).days < 30:
                        if verbose: print(f"Data for UID {id} already exists in cache. Skipping retrieval...")
                        status_message += f"{todays_date}: Data for UID {id} already exists in {persist_dir}. Skipped. "
                        works.append(_work)
                        was_resently_persisted = True
                        break # Exit the for loop if a match was found.
                    else:
                        if verbose: print(f"Data for UID {id} exists in cache but is older than 30 days. Retrieving updated data...")
                        status_message += _work["status_messages"] # Prepend the status messages from the persisted data.
                        status_message += f"{todays_date}: Data for UID {id} exists in {persist_dir} but is older than 30 days. Retrieving updated data. "
            if was_resently_persisted:
                continue # Skip to the next iteration if the data was recently persisted.
                # TODO: This may require revision. If the metadata were persisted, the PDF file may not have been saved. This should be checked and handled.

        # The following block of code is used to handle the API rate limit. The OpenAlex API has a rate limit of 10 requests per second.
        if iter_count > 9:
            time_delta = datetime.now() - now # Calculate the time taken for 10 requests. Sleep if the time taken is less than 1 second. Rate limit is 10 requests per second.
            if time_delta < timedelta(seconds=1):  # Compare with timedelta object of 1 second.
                remaining_time = 1 - time_delta.total_seconds() # Calculate the remaining time to sleep.
                if verbose: print(f"Number of requests reached 10. Sleeping for {round(remaining_time, 3)} seconds...")
                time.sleep(remaining_time) # Sleep for the remaining time.
                iter_count = 0 # Reset the counter after sleeping.
                now = datetime.now() # Reset the time after sleeping.

        # Construct the URL for the API call based on the ID type.
        if re.match(doi_regex, id):
            url = f"{base_url}https://doi.org/{id}"
        elif id.isdigit():
            url = f"{base_url}pmid:{id}"
        elif id.startswith("PMC"):
            url = f"{base_url}pmcid:{id}"
        elif id.startswith("W"):
            url = id.replace("W", "https://api.openalex.org/W")
        else:
            if verbose: print(f"Invalid ID: {id}. Skipping...")
            failed_calls.append({"uid": id, "error": "Invalid ID"})
            continue # Skip to the next iteration if the ID is invalid.

        # Retrieve data for the work (e.g., journal article, book, dataset, and theses) using the OpenAlex API.
        try: 
            response = requests.get(url, params=params)    
        except requests.RequestException as e:
            if verbose: print(f"An error occurred while making an API call with UID {id}: {e}")
            failed_calls.append({"uid": id, "error": f"Exception during API call: {e}"})
            continue # Skip to the next iteration if an error occurs while making the API call.

        # Handle unsuccessful API calls.    
        if response.status_code != 200: 
            if verbose: print(f"API call for work with UID {id} was not successful. Status code: {response.status_code}")
            failed_calls.append({"uid": id, "error": f"API call not successful. Status code: {response.status_code}"})
            continue # Skip to the next iteration if the API call was unsuccessful.

        # Continue if the API call was successful.
        else:    
            data = response.json()
            status_message += f"{todays_date}: Successfully retrieved metadata with UID {id}. "
            if verbose: print(f"Successfully retrieved metadata for work with UID {id}.")

            # Download the PDF file of the article if a directory path is provided and if it is openly accessable.
            if not pdf_output_dir:
                if verbose: print("Output directory for PDF files not provided. Skipping download...")
                status_message += f"{todays_date}: Output directory for PDF files not provided. Skipped download. "
            else:
                try:
                    message, pdf_path = download_pdf(data, pdf_output_dir, email=email, enable_selenium=enable_selenium, is_headless=is_headless, verbose=verbose) # Download the PDF file of the article if a directory path is provided and if it is openly accessable; update the status message.
                    status_message += message

                except Exception as e:
                    # TODO: fix a bug: An error occurred while attempting to download the PDF for work with UID 10.1126/sciimmunol.aau8714: cannot access local variable 'filename' where it is not associated with a value. Make sure the download_pdf function is imported from the openalex_api_utils module and is working correctly.
                    # This is only raised for works with UID 10.1126/sciimmunol.aau8714 and UID 30143481
                    print(f"An error occurred while attempting to download the PDF for work with UID {id}: {e}. Make sure the download_pdf function is imported from the openalex_api_utils module and is working correctly.")

            work = {
                    "uid": id, # Unique identifier of the work; can be a DOI, PMID, PMCID, or OpenAlex ID.
                    "entry_types": [entry_type], # Type of entry retrieved (e.g., primary entry, reference of primary entry, citing primary entry, related to primary entry). List of strings to allow multiple types.
                    "metadata": data, # Metadata of the work retrieved from the API.
                    "pdf_path": pdf_path, # Path to the PDF file if available. Is None if the PDF was not downloaded.
                    "status_messages": status_message, # Status messages for the work.
                    "persist_datetime": persist_datetime, # Datetime when the data was saved to the cache.
                }

            # Save the JSON response for the work if a directory path is provided for persistence.
            if persist_dir:
                status = persist_data_to_disk(work, persist_dir)
                if verbose: 
                    if status:
                        print(f"Successfully saved metadata for work with UID {id} to cache.")

        # Append the work data to the works list.
        works.append(work)

        # Increment the iteration counter.
        iter_count += 1
        
    if verbose: print("***\nFinished retrieving works.\n")

    return works, failed_calls

## Example usage:
# uids = ['38860170', '38857748','https://openalex.org/W1997963236','10.1186/s12967-023-04576-8']
# email = os.environ.get("EMAIL")
# Retrieve works without saving PDFs or cache
# works, failed_calls = get_works(uids, email=email, show_progress=True)
# Retrieve works and save PDFs, cache the JSON responses
# works, failed calls = get_works(uids, email=email, pdf_output_dir="./pdfs", persist_dir="./cache", show_progress=True)



import os
import requests
from datetime import datetime

def download_pdf(data: dict, pdf_output_dir: str, email: str, enable_selenium: bool = False, is_headless: bool = True, verbose: bool = False) -> tuple[str, str]:
    """
    Download a single PDF file from a URL and save it to the specified directory.

    Args:
        data (dict): Dictionary containing information about a single work, obtained from the OpenAlex API. It should contain the 'best_oa_location' key with the 'pdf_url' value.
        pdf_output_dir (str): Directory to save the PDFs.
        email (str): Email address to use in the request.
        enable_selenium (bool, optional): If True, enables the use of Selenium for downloading PDFs. Defaults to False. Install the Chrome browser and the Chrome WebDriver to use this option.
            Note: Enabling Selenium can add a delay.
            This option is only used for open access works that cannot be downloaded using the requests library. 
        is_headless (bool, optional): If True, runs the browser in headless mode (i.e, without any visible UI). Defaults to True.
        verbose (bool): If True, prints detailed status messages. Default is False.

    Returns:
        status_message (str): Status message for the download operation.
        filepath (str): Filepath of the downloaded PDF file, or None if download was unsuccessful.
    """

    # print("Calling download_pdf function...") # Uncomment this line for debugging

    # Define the current date, which is used in the status message.
    todays_date = datetime.now().date()

    # Initialize variables.
    pdf_response = None
    status_message = ""
    pdf_filepath = None

    # Make a directory to save the PDFs if it does not exist.
    if not os.path.exists(pdf_output_dir):
        os.makedirs(pdf_output_dir)

    # Extract the OpenAlex ID, PMID and DOI from the data dictionary. This is used to generate a unique filename for the PDF file to be saved.
    oaid = data['id'].split('/')[-1]
    try:
        pmid = data['ids'].get('pmid', '?').split('/')[-1]
    except KeyError:
        pmid = "?"
    try:
        doi = data['ids'].get('doi', '')
        if doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "").replace("/", "#")
    except KeyError:
        doi = "?"
    
    pdf_filename = f"{pmid}_{doi}_{oaid}.pdf"
    pdf_filepath = os.path.join(pdf_output_dir, pdf_filename)
    # print(f"PDF file path: {pdf_filepath}") # Uncomment this line for debugging

    # Check if the work is open access and has a PDF URL.
    if 'best_oa_location' not in data or not data['best_oa_location'] or not data['best_oa_location'].get('is_oa', False):
        if verbose:
            print(f"Work with UID {data['id']} is not open access or 'best_oa_location' key not found. Skipping download of PDF...")
        status_message += f"{todays_date}: Work with UID {data['id']} is not open access or 'best_oa_location' key not found. Skipped PDF download. "
        return status_message, None

    if verbose:
        print(f"Work with UID {data['id']} is open access. Checking for PDF URL...")

    pdf_url = data['best_oa_location'].get('pdf_url', None)
    if not pdf_url:
        if verbose:
            print("No PDF URL was found in the API call response. Skipping download of PDF...")
        status_message += f"{todays_date}: PDF URL not found in API call response. Skipped PDF download. "
        return status_message, None

    # Proceed to download the PDF file.
    if verbose:
        print(f"Trying to download PDF from {pdf_url}...")
    try:
        pdf_response = requests.get(pdf_url, params={"mailto": email}, stream=True)
    except requests.RequestException as e:
        if verbose:
            print(f"An error occurred while attempting to download {data['id']} from {pdf_url}: {e}")
        status_message += f"{todays_date}: Error during request to {pdf_url}: {e}. "
        return status_message, None

    # Handle the case if pdf_response has no status_code attribute.
    if not hasattr(pdf_response, 'status_code'):
        if verbose:
            print(f"Failed to download from {pdf_url}. Status code not found.")
        status_message += f"{todays_date}: Failed to download PDF from {pdf_url}. Status code not found. "
        return status_message, None

    if pdf_response.status_code == 200:
        try:
            with open(pdf_filepath, 'wb') as file:
                for chunk in pdf_response.iter_content(1024):  # Write the content of the response in chunks of 1024 bytes, for memory efficiency.
                    if chunk:  # Filter out keep-alive new chunks.
                        file.write(chunk)
            if verbose:
                print(f"Successfully saved {pdf_filename} to {pdf_output_dir}.")
            status_message += f"{todays_date}: PDF saved to {pdf_filepath}. "
            return status_message, pdf_filepath
        except Exception as e:
            if verbose:
                print(f"An error occurred while attempting to save {pdf_filename} to {pdf_output_dir}: {e}")
            status_message += f"{todays_date}: Error while saving PDF to {pdf_filepath}: {e}. "
            return status_message, None

    if pdf_response.status_code == 403:
        if not enable_selenium:
            if verbose:
                print(f"Failed to download from {pdf_url}. Status code: {pdf_response.status_code}. Selenium disabled.")
            status_message += f"{todays_date}: Failed to download PDF from {pdf_url}. Status code: {pdf_response.status_code}. Selenium disabled. "
            return status_message, None
        else:
            if verbose:
                print(f"Failed to download from {pdf_url}. Status code: {pdf_response.status_code}. Trying with Selenium...")
            # Try using selenium to download the PDF
            # First, try to download PDF using Selenium and the PubMed Central URL if available.
            pmcid = data.get('ids', {}).get('pmcid', None)
            if pmcid:
                pmcid = f"PMC{pmcid.split('/')[-1]}"
                pmc_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
                if verbose:
                    print(f"Trying to download PDF from {pmc_url}...")
                try:
                    _status_message, pdf_filepath = download_pdf_with_selenium(pmc_url, pdf_filepath, is_headless=is_headless, verbose=verbose)  # Call the function with the url to PubMed Central
                    if pdf_filepath:
                        status_message += _status_message
                        return status_message, pdf_filepath
                    else:
                        status_message += _status_message
                except Exception as e:
                    if verbose:
                        print(f"An error occurred while attempting to download PDF from {pmc_url} using Selenium: {e}")
                    status_message += f"{todays_date}: Error during PDF download from {pmc_url} using Selenium: {e}. "

            # Next, try to download PDF using Selenium using the best_oa_location URL (not PubMed Central URL)
            if verbose:
                print(f"Trying to download PDF from {pdf_url} using Selenium...")
            try:
                _status_message, pdf_filepath = download_pdf_with_selenium(pdf_url, pdf_filepath, is_headless=is_headless, verbose=verbose)  # Call the function with the url to the best_oa_location (journal website)
                if pdf_filepath:
                    status_message += _status_message
                    return status_message, pdf_filepath
                else:
                    status_message += _status_message
                    return status_message, None
            except Exception as e:
                if verbose:
                    print(f"An error occurred while attempting to download PDF from {pdf_url} using Selenium: {e}")
                status_message += f"{todays_date}: Error during PDF download from {pdf_url} using Selenium: {e}. "
                return status_message, None

    # Handle other unsuccessful download requests or if Selenium is not enabled.
    else:
        if verbose:
            print(f"Failed to download from {pdf_url}. Status code: {pdf_response.status_code}")
        status_message += f"{todays_date}: Failed to download PDF from {pdf_url}. Status code: {pdf_response.status_code}. "
        return status_message, None

# Example usage
# status_message, pdf_filepath = download_pdf(data, pdf_output_dir, email, verbose)



from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import time
import os
import shutil

def download_pdf_with_selenium(pdf_url: str, pdf_filepath: str, is_headless: bool = True, verbose: bool = False) -> tuple[str, str | None]:
    """Downloads a PDF from a given URL using Selenium WebDriver with Chrome.

    The function checks for directory and URL validity, uses the Selenium WebDriver with Chrome to open the URL,
    and downloads the PDF, and saves it to the specified directory. The browser can run
    either in headless mode (unattended environment without any visible UI) or in standard mode (with a visible UI), 

    Args:
        pdf_url (str): The URL of the PDF to download.
        pdf_filepath (str): The path to save the downloaded PDF.
        is_headless (bool): If True, the browser runs in headless mode (no visible UI). 
        verbose (bool): If True, print messages about the download process.

    Returns:
        tuple[str, str | None]: A tuple containing the status message and the file path of the downloaded PDF.
    """

    # Initialize variables
    downloaded_file = None
    status_message = ""
    todays_date = datetime.now().date()

    # Input validation
    if not isinstance(pdf_url, str):
        raise ValueError("pdf_url must be a string.")
    if not pdf_url.startswith("http"):
        raise ValueError("Invalid URL")
    if not isinstance(pdf_filepath, str):
        raise ValueError("pdf_filepath must be a string.")
    if not pdf_filepath.endswith('.pdf'):
        raise ValueError("pdf_filepath must end with '.pdf'")
    if not isinstance(is_headless, bool):
        raise ValueError("is_headless must be a boolean value.")
    if not isinstance(verbose, bool):
        raise ValueError("verbose must be a boolean value.")
    
    # Extract directory from file path
    pdf_output_dir = os.path.abspath(os.path.dirname(pdf_filepath))
    filename = os.path.basename(pdf_filepath)
    
    # Create output directory if it doesn't exist
    if not os.path.isdir(pdf_output_dir):
        os.makedirs(pdf_output_dir)

    # Configure Chrome options
    options = Options()
    if is_headless:
        options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_experimental_option('prefs', {
        "download.default_directory": pdf_output_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True
    })

    # Initialize Chrome WebDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        # Download the PDF
        download_start_time = time.time()  # Record the start time of the download
        driver.get(pdf_url)  # Open the URL using the WebDriver

        # Wait for download to complete with a timeout
        timeout = 30
        downloaded_file = None
        while timeout > 0:
            downloaded_files = [f for f in os.listdir(pdf_output_dir) if f.endswith('.pdf') or f.endswith('.crdownload')]
            for file in downloaded_files:
                file_path = os.path.join(pdf_output_dir, file)
                file_creation_time = os.path.getctime(file_path)
                if file_creation_time >= download_start_time and time.time() - file_creation_time <= 60:  # Check if the file was created within the last 60 seconds
                    if file.endswith('.crdownload'):
                        # Check if the crdownload file is still being written to
                        if time.time() - os.path.getctime(file_path) > 1:
                            # Download still in progress, continue waiting
                            continue
                    elif file.endswith('.pdf'):
                        downloaded_file = file_path
                        # Cleanup step to remove the .crdownload file if it exists
                        crdownload_file = file_path + '.crdownload'
                        if os.path.exists(crdownload_file):
                            os.remove(crdownload_file)
                        break
            if downloaded_file:
                break
            time.sleep(1)
            timeout -= 1

        if downloaded_file:
            new_filepath = pdf_filepath
            # Check if the file already exists and add logic to avoid overwriting files with the same name
            if os.path.exists(pdf_filepath):
                if os.path.getctime(downloaded_file) >= download_start_time:  # Check if the file was created after the download started
                    counter = 1
                    while os.path.exists(f"{pdf_filepath[:-4]}({counter}).pdf"):  # Only add a counter if a file with the same name already exists
                        counter += 1
                    new_filepath = f"{pdf_filepath[:-4]}({counter}).pdf"
                    status_message += f"File {pdf_filepath} already exists. Renamed to {new_filepath}. "
                else:
                    new_filepath = pdf_filepath
                    status_message += f"Renamed {downloaded_file} to {new_filepath}. "

            shutil.move(downloaded_file, new_filepath)
            status_message += f"{todays_date}: PDF downloaded successfully and saved as {new_filepath}. "
            if verbose:
                print(f"PDF downloaded successfully and saved as {new_filepath}.")
            return status_message, new_filepath
        else:
            status_message = f"{todays_date}: PDF download from {pdf_url} using Selenium with headless mode set to {is_headless} failed. "
            if verbose:
                print(f"PDF download from {pdf_url} using Selenium with headless mode set to {is_headless} failed.")
            return status_message, None

    except Exception as e:
        status_message = f"{todays_date}: An error occurred while attempting to download PDF from {pdf_url} using Selenium with headless mode set to {is_headless}: {e} "
        if verbose:
            print(f"An error occurred while attempting to download PDF from {pdf_url} using Selenium with headless mode set to {is_headless}: {e}")
        return status_message, None

    finally:
        # Close the browser
        driver.quit()
    
# Example usage:
# in headless mode
# pdf_url1 = "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6341984/pdf/"
# pdf_filepath1 = "./pdfs/PMC6341984.pdf"
# status_message, pdf_filepath = download_pdf_with_selenium(pdf_url1, pdf_filepath1, is_headless=True, verbose=True)
# or with visible UI
# pdf_url2 = "http://www.cell.com/article/S0092867422015811/pdf"
# pdf_filepath2 = "./pdfs/PMC9907019.pdf"
# status_message, pdf_filepath = download_pdf_with_selenium(pdf_url2, pdf_filepath2, is_headless=False, verbose=True)



def persist_data_to_disk(work: dict, persist_dir: str) -> bool:
    """
    Save the JSON response for a work to the specified directory.

    Args:
        work (dict): Dictionary containing information about the work.
        persist_dir (str): Directory to save the JSON response for the work.

    Returns:
        bool: True if the data was successfully saved, False otherwise.
    """
    # Initialize variables.
    persist_datetime = None
    status = False

    # Make a directory to save the JSON responses if it does not exist.
    if not os.path.exists(persist_dir): 
        os.makedirs(persist_dir)

    # Extract the OpenAlex ID, PMID and DOI from the metadata. This is used to generate unique filenames for the JSON files.
    oaid = work['metadata']['id'].split('/')[-1] 
    try:
        pmid = work['metadata']['ids'].get('pmid', '?').split('/')[-1] # Extract the PMID from the metadata. The try-except block is used to handle cases where the 'ids' key is not present.
    except Exception:
        pmid = "?"
    try:
        doi = work['metadata']['ids'].get('doi', '?') # Extract the DOI from the metadata. The try-except block is used to handle cases where the 'ids' key is not present.
        if doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "") # Remove the prefix from the DOI.
            doi = doi.replace("/", "#") # Replace the forward slash with a hash symbol to avoid issues with file paths.
        # print(doi) # Uncomment this line for debugging
    except Exception:
        doi = "?"

    # Update the 'persist_datetime' field in the work dictionary.
    work["persist_datetime"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")

    # Construct the filename for the JSON file.
    filename_json = f"{pmid}_{doi}_{oaid}.json"

    # Save the JSON response for the work to the specified directory.
    try:
        with open(os.path.join(persist_dir, filename_json), "w") as f:
            f.write(json.dumps(work, indent=4))
            status = True
    except Exception as e:
        print(f"An error occurred while attempting to save {filename_json} using persist_data_to_disk(): {e}.")
    
    return status

# Example usage
# status = persist_data_to_disk(work, persist_dir)



def load_works_from_storage(persist_dir: str) -> List[Dict[str, Any]]:
    """
    Load the JSON responses for works from the specified directory.

    Args:
        persist_dir (str): Directory containing the JSON responses for the works.

    Returns:
        List[Dict[str, Any]]: List of dictionaries containing information about the works.
    """
    # Initialize the list of works.
    works = []

    # Check if the directory exists.
    if os.path.exists(persist_dir):
        # Get the list of files in the directory.
        files = os.listdir(persist_dir)

        # Filter the files to include only JSON files.
        files = [file for file in files if file.endswith(".json")]

        # Check if there are any files in the directory.
        if not files:
            print(f"No files found in {persist_dir}.")
            return works

        # Iterate over the files in the directory.
        for filename in files:
            # Load the data from each file.
            with open(os.path.join(persist_dir, filename), "r") as f:
                data = json.load(f)
                works.append(data)

        # Ensure that works have the required fields, such as 'persist_datetime', 'uid', and 'metadata', otherwise remove them from the list.
        works = [work for work in works if "persist_datetime" in work and "uid" in work and "metadata" in work]

    return works

## Example usage:
# works_from_storage = load_works_from_storage(persist_dir)



# import requests
# from tqdm import tqdm
# from datetime import datetime
# from typing import List, Dict, Any, Optional

def get_citations(works: List[Dict[str, Any]], email: str, per_page: int = 200, pdf_output_dir: Optional[str] = None, persist_dir: Optional[str] = None, enable_selenium: bool = False, is_headless: bool = True, show_progress: bool = False, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Retrieve works that cite the given works.

    Parameters:
    works (List[Dict[str, Any]]): List of works to retrieve citations for.
    email (str): Email address to be passed to the API.
    per_page (int): Number of results per page (default is 200).
    pdf_output_dir (Optional[str]): Directory to save PDFs (default is None).
    persist_dir (Optional[str]): Directory to persist data (default is None).
    enable_selenium (bool): If True, use Selenium for downloading PDFs (default is False).
    is_headless (bool): If True, run the browser in headless mode (i.e., without any visible UI) (default is True).
    show_progress (bool): If True, show progress (default is False).
    verbose (bool): If True, print progress statements (default is False).

    Returns:
    List[Dict[str, Any]]: List of works that cite the given works.
    """

    # Input validation
    assert isinstance(per_page, int), "per_page must be an integer."
    assert 0 < per_page <= 200, "per_page must be greater than 0 and less than or equal to 200."
    assert isinstance(pdf_output_dir, str) or pdf_output_dir is None, "pdf_output_dir must be a string or None."
    assert isinstance(persist_dir, str) or persist_dir is None, "persist_dir must be a string or None."
    assert isinstance(show_progress, bool), "show_progress must be a boolean value."
    assert isinstance(verbose, bool), "verbose must be a boolean value."

    # Initialize variables
    citations = []  # List to store the works that cite the retrieved works.
    citations_metadata = []  # List to store the metadata of the cited by works.
    todays_date = datetime.now().date()

    # Handle the case where works is a single work, i.e. a dictionary; convert it to a list of works.
    if not isinstance(works, list):
        works = [works]
        if verbose: print("Only one work provided. Converting to a list of works.")

    # Display a progress bar if show_progress is True
    if show_progress:
        iterable = tqdm(works, desc="Retrieving citations")
    else:
        iterable = works

    # Iterate over each work in the list to retrieve the works that cite them.
    for work in iterable:
        if not isinstance(work, dict) or 'metadata' not in work or 'cited_by_count' not in work['metadata']:
            continue  # Skip invalid work entries

        cited_by_count = work['metadata']['cited_by_count']
        short_title = work['metadata']['title'][:50] + "..." if len(work['metadata']['title']) > 50 else work['metadata']['title']
        if cited_by_count != 0:
            cited_by_batches = [cited_by_count - i for i in range(0, cited_by_count, per_page)]
            for i, batch in enumerate(cited_by_batches):
                if verbose:
                    print(f"Processing batch {i+1} of {len(cited_by_batches)} ({cited_by_count} citations) for '{short_title}' from {work['metadata']['cited_by_api_url']} ...")
                try:
                    response = requests.get(work['metadata']['cited_by_api_url'], params={"mailto": email, "per_page": per_page, "page": i+1})
                    if response.status_code == 200:
                        citations_metadata.extend(response.json()['results'])
                    else:
                        if verbose:
                            print(f"API call failed with status code {response.status_code}.")
                except requests.RequestException as e:
                    if verbose:
                        print(f"An error occurred while making an API call: {e}")

    # Display a progress bar if show_progress is True
    if show_progress:
        citations_metadata = tqdm(citations_metadata, desc="Processing citations")  # Wrap the list of citations with tqdm to display a progress bar.
    
    # Process the metadata to create a list of works, similar to the get_works function
    for data in citations_metadata:
        work = {
            "uid": data['id'],
            "metadata": data,
            "entry_types": ["citing primary entry"],
            "pdf_path": None,
            "status_messages": "",
            "persist_datetime": None,
        }
        citations.append(work)

    if pdf_output_dir:
        if show_progress:
            iterable2 = tqdm(citations, desc="Retrieving PDFs")
        else:
            iterable2 = citations
        for work in iterable2:
            if not 'best_oa_location' in work['metadata'] or not work['metadata']['best_oa_location'] or not work['metadata']['best_oa_location'].get('is_oa', False):
                if verbose: print(f"Work with UID {work['uid']} is not open access. Skipping download of PDF...")
                work["pdf_path"] = None
                work["status_messages"] = f"{todays_date}:Work is not open access. Skipped PDF download;"
            else:
                try:
                    message, pdf_path = download_pdf(work['metadata'], pdf_output_dir, email=email, enable_selenium=enable_selenium, is_headless=is_headless, verbose=verbose)
                    work["pdf_path"] = pdf_path
                    work["status_messages"] = message
                except Exception as e:
                    print(f"An error occurred while attempting to download the PDF for work with UID {work['uid']}: {e}. Make sure the download_pdf function is imported from the openalex_api_utils module and is working correctly.")
                    work["pdf_path"] = None
                    work["status_messages"] = f"{todays_date}:Error during PDF download: {e};"
    
    if persist_dir:
        if show_progress:
            iterable2 = tqdm(citations, desc="Persisting data")
        else:
            iterable2 = citations
        for work in iterable2:
            status = persist_data_to_disk(work, persist_dir)
            if verbose:
                if status:
                    print(f"Successfully saved metadata for work with UID {work['uid']} to cache.")

    assert all(isinstance(work, dict) for work in citations), "Must be a list of dictionaries."
    # assert all(key in works[0].keys() for key in citations[0].keys()), "All keys in citations must be present in works."
    assert all("citing primary entry" in work['entry_types'] for work in citations), "All entry_types in citations must contain 'citing primary entry'."

    if verbose:
        print("Actual number of works citing the primary works (result of API calls):", len(citations))

    return citations

# Example usage:
# citations = get_citations(works, email=EMAIL, per_page=200, enable_selenium=True, show_progress=True)



# from typing import List, Dict, Any
from IPython.display import display, HTML

def list_works(works: List[Dict[str, Any]]) -> None:
    """
    List information about works retrieved from the OpenAlex API.

    Args:
        works: List of dictionaries containing information about the works.

    Returns:
        None
    """
    for work in works:
        # Extract relevant information about the work.
        first_author_last_name = work['metadata']['authorships'][0]['author']['display_name'].split(' ')[-1]
        title = work['metadata']['title']
        publication_year = work['metadata']['publication_year']
        journal = work['metadata']['primary_location']['source']['display_name']
        primary_topic = work['metadata']['primary_topic']['display_name']
        primary_topic_score = work['metadata']['primary_topic']['score']
        cited_by_api_url = work['metadata']['cited_by_api_url']
        cited_by_ui_url = cited_by_api_url.replace("api.openalex.org", "openalex.org")
        cited_by_count = work['metadata']['cited_by_count']
        has_fulltext = work['metadata']['has_fulltext']
        is_oa = work['metadata']['open_access']['is_oa']
        
        try:
            pdf_url = work['metadata']['best_oa_location']['pdf_url']
        except KeyError:
            pdf_url = ''
        
        try:
            landing_page_url = work['metadata']['best_oa_location']['landing_page_url']
        except KeyError:
            landing_page_url = ''

        # Lock symbols, to indicate if the work is open access or not.
        open_lock = "\U0001F513"  # 🔓
        closed_lock = "\U0001F512"  # 🔒

        # Symbols, to indicate if full text is available or not.
        full_text = "\U0001F4D6"  # 📖
        no_full_text = "\U0001F4D1"  # 📑

        # HTML for Download PDF and Read Full Text links
        pdf_link = f"<a href='{pdf_url}' target='_blank'>Download PDF</a>" if pdf_url else "PDF not available"
        full_text_link = f"<a href='{landing_page_url}' target='_blank'>Read Full Text</a>" if landing_page_url else "Full text not available"

        display(
            HTML(f"{first_author_last_name} <i>et al.</i> <b>{title}.</b> {journal} {publication_year}"),
            HTML(f"<a href='{cited_by_ui_url}' >Cited by</a>: {cited_by_count} | References: {len(work['metadata']['referenced_works'])} | Related works: {len(work['metadata']['related_works'])}"), 
            # HTML(f"Primary topic: {primary_topic} (Score: {primary_topic_score})"),
            HTML(f"{pdf_link} &nbsp; {full_text_link} &nbsp; {open_lock if is_oa else closed_lock} &nbsp; {full_text if has_fulltext else no_full_text}"),
            HTML("<hr>")
        )

## Example usage:
# display_works(works)




def get_open_access_ids(works: List[Dict[str, Any]]) -> List[int]:
    """
    Filter the list of works to return the works that are open access.

    Parameters:
    works (list): List of works to count the number of open access works. Each work is a dictionary containing metadata.

    Returns:
    open_access_ids (list): List of IDs of works that are open access.
    """
    # Input validation.
    assert all(isinstance(work, dict) for work in works), "Works must be a list of dictionaries."
    assert all("metadata" in work for work in works), "Work dictionary must contain a 'metadata' key."
    assert all("open_access" in work["metadata"] for work in works), "Metadata must contain an 'open_access' key."
    assert all("is_oa" in work["metadata"]["open_access"] for work in works), "Open access metadata must contain an 'is_oa' key."
    assert all(isinstance(work["metadata"]["open_access"]["is_oa"], bool) for work in works), "Value of 'is_oa' must be a boolean."

    open_access_ids = [work['metadata']['id'] for work in works if work['metadata']['open_access']['is_oa']]
    return open_access_ids

## Example usage:
# open_access_ids = get_open_access_ids(works)



import plotly.graph_objects as go
from plotly.subplots import make_subplots

def plot_open_access_stats(works_dict: dict) -> None:
    """
    Plot the distribution of open access and non-open access statistics as pie charts in subplots.

    Args:
    works_dict: Dictionary containing the subplot titles and the works data.

    Returns:
    None
    """
    # Create subplots.
    fig = make_subplots(rows=2, cols=2, subplot_titles=list(works_dict.keys()),
                        specs=[[{'type': 'domain'}, {'type': 'domain'}],
                               [{'type': 'domain'}, {'type': 'domain'}]])

    for i, (title, data) in enumerate(works_dict.items(), 1):
        open_access_ids = get_open_access_ids(data)
        data_dict = {'Category': ['Open Access', 'Not Open Access'], 
                     'Values': [len(open_access_ids), len(data) - len(open_access_ids)]}

        # Add pie charts to subplots.
        fig.add_trace(go.Pie(labels=data_dict['Category'], values=data_dict['Values'], name=title), 
                      row=(i+1)//2, col=(i+1)%2 + 1)

    # Update layout.
    fig.update_layout(title_text="Open Access Statistics", height=600, width=600)

    # Show plot.
    fig.show()
   
## Example usage:
# works_dict = {"Primary Works": works, "References": references, "Related Works": related_works, "Citations": citations}
# plot_open_access_stats(works_dict)
