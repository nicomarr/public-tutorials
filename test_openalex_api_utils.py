import unittest
from unittest.mock import patch, mock_open, MagicMock
import tempfile
import os
import json
from datetime import datetime
import requests
import sys
sys.path.append("..")
from openalex_api_utils.core import *
import unittest
from IPython.display import display, HTML

class TestGetWorks(unittest.TestCase):

    @patch('openalex_api_utils.core.requests.get')
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

    @patch('openalex_api_utils.core.requests.get')
    def test_get_works_invalid_ids(self, mock_get):
        email = "test@example.com"
        invalid_uids = ["invalid_id", "https://invalid_doi.org/10.1234/invalid_doi"]

        works, failed_calls = get_works(invalid_uids, email=email, verbose=False)
        
        self.assertEqual(len(works), 0)  # No valid works should be retrieved
        self.assertEqual(len(failed_calls), 2)  # Both API calls should fail

    @patch('openalex_api_utils.core.requests.get')
    def test_get_works_exceptions(self, mock_get):
        email = "test@example.com"
        uids = ['1234567', '1000000']

        # Create a mock response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = json.dumps({"error": "Not Found", "message": "Resource not found"})
        mock_get.return_value = mock_response

        works, failed_calls = get_works(uids, email=email, verbose=False)
        
        assert len(works) == 0, "No works should be retrieved if the API request fails."
        assert len(failed_calls) == 2, "Both API calls should fail."
        for call in failed_calls:
            assert call['status_code'] == 404
            assert call['error'] == "Not Found"
            assert call['message'] == "Resource not found"

        # Test JSON parsing error
        mock_response.text = "Invalid JSON"
        works, failed_calls = get_works(uids, email=email, verbose=False)
        
        assert len(works) == 0
        assert len(failed_calls) == 2
        for call in failed_calls:
            assert call['status_code'] == 404
            assert call['error'] == "JSONDecodeError"


class TestListWorks(unittest.TestCase):
    
    @patch('IPython.display.display')
    def test_list_works(self, mock_display):
        # Sample data for testing
        works = [
            {
                'metadata': {
                    'authorships': [{'author': {'display_name': 'John Doe'}}],
                    'title': 'Sample Work',
                    'publication_year': 2021,
                    'primary_location': {'source': {'display_name': 'Sample Journal'}},
                    'primary_topic': {'display_name': 'Sample Topic', 'score': 0.85},
                    'cited_by_api_url': 'https://api.openalex.org/works/12345',
                    'cited_by_count': 10,
                    'has_fulltext': True,
                    'open_access': {'is_oa': True},
                    'best_oa_location': {
                        'pdf_url': 'https://example.com/sample.pdf',
                        'landing_page_url': 'https://example.com/fulltext'
                    },
                    'referenced_works': [1, 2, 3],
                    'related_works': [4, 5]
                }
            },
            {
                'metadata': {
                    'authorships': [{'author': {'display_name': 'Jane Smith'}}],
                    'title': 'Another Work',
                    'publication_year': 2020,
                    'primary_location': {'source': {'display_name': 'Another Journal'}},
                    'primary_topic': {'display_name': 'Another Topic', 'score': 0.9},
                    'cited_by_api_url': 'https://api.openalex.org/works/67890',
                    'cited_by_count': 5,
                    'has_fulltext': False,
                    'open_access': {'is_oa': False},
                    'best_oa_location': {},
                    'referenced_works': [6, 7],
                    'related_works': [8, 9]
                }
            }
        ]


if __name__ == '__main__':
    unittest.main()
