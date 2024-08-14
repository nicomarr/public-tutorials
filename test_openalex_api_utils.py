import unittest
from unittest.mock import patch, mock_open, MagicMock
import tempfile
import os
from datetime import datetime
from IPython.display import display, HTML
from openalex_api_utils import *

class TestGetWorks(unittest.TestCase):

    @patch('openalex_api_utils.requests.get')
    def test_get_works_basic(self, mock_get):
        # Mock API response for a successful request
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'id': 'https://openalex.org/W000000000',
            'best_oa_location': {
                'is_accepted': True,
                'is_oa': True,
                'is_published': True,
                'pdf_url': 'https://onlinelibrary.wiley.com/doi/pdfdirect/000/000',
            },
            'ids': {
                'doi': 'https://doi.org/10.1111/00000000',
                'pmid': '1234567',
            }
        }
        mock_get.return_value = mock_response

        email = "test@example.com"
        uids = ['1234567', 'https://openalex.org/W12345678', 'W11111111', '10.1111/s12345-678-9012-3', 'https://doi.org/10.1111/s01234-567-890-0'] 
        pdf_output_dir = tempfile.mkdtemp()
        persist_dir = tempfile.mkdtemp()

        works, failed_calls = get_works(uids, email=email, pdf_output_dir=pdf_output_dir, persist_dir=persist_dir, verbose=False)

        self.assertEqual(len(works), len(uids)) # Assert that the number of works retrieved matches the number of input IDs
        self.assertTrue(all(isinstance(work, dict) for work in works)) # Assert that each work is a dictionary
        self.assertTrue(all("uid" in work for work in works)) # Assert that each work dictionary contains a 'uid' key
        self.assertTrue(all("metadata" in work for work in works)) # Assert that each work dictionary contains an 'metadata' key
        self.assertTrue(all("pdf_path" in work for work in works)) # Assert that each work dictionary contains a 'pdf_path' key
        self.assertTrue(all("status_messages" in work for work in works)) # Assert that each work dictionary contains a 'status_messages' key
        self.assertTrue(all("persist_datetime" in work for work in works)) # Assert that each work dictionary contains a 'persist_datetime' key
        self.assertTrue(all("pdf_url" in work['metadata']['best_oa_location'] for work in works)) # Assert that each work contains a 'pdf_url' key in the 'best_oa_location' field
        self.assertTrue(all("doi" in work['metadata']['ids'] for work in works)) # Assert that each work contains a 'doi' key in the 'ids' field
        self.assertTrue(all("id" in work['metadata'] for work in works)) # Assert that each work contains an 'id' as inner key in the 'metadata' outer key
        self.assertTrue(all("pmid" in work['metadata']['ids'] for work in works)) # Assert that each work contains a 'pmid' key in the 'ids' field
        self.assertEqual(len(failed_calls), 0) # Assert that there are no failed API calls

        # Clean up temporary directories
        for file in os.listdir(pdf_output_dir):
            os.remove(os.path.join(pdf_output_dir, file))
        os.rmdir(pdf_output_dir)
        for file in os.listdir(persist_dir):
            os.remove(os.path.join(persist_dir, file))
        os.rmdir(persist_dir)

    @patch('openalex_api_utils.requests.get')
    def test_get_works_invalid_ids(self, mock_get):
        email = "test@example.com"
        invalid_uids = ["invalid_id", "https://invalid_doi.org/10.1234/invalid_doi"]

        works, failed_calls = get_works(invalid_uids, email=email, verbose=False)
        
        self.assertEqual(len(works), 0)  # No valid works should be retrieved
        self.assertEqual(len(failed_calls), 2)  # Both API calls should fail

    @patch('openalex_api_utils.requests.get')
    def test_get_works_exceptions(self, mock_get):
        email = "test@example.com"
        uids = ['1234567','1000000']

        # Mock API response for a failed request
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        # Mock API request exception
        works, failed_calls = get_works(uids, email=email, verbose=False)
        assert len(works) == 0, "No works should be retrieved if the API request fails."
        assert len(failed_calls) == 2, "Both API calls should fail."

if __name__ == '__main__':
    unittest.main()