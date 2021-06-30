"""
Google Photos client used to retrieve all necessary data from the
server.
"""
#pylint: disable=no-member
import requests

from googleapiclient.discovery import build, Resource
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

class PhotosClient:
    """
    Google Photos client used for obtaining necessary information
    about the user's photo library.
    """

    def __init__(self, credentials):
        self.google_photos: Resource = None
        self.credentials = Credentials(
            token=credentials["token"],
            refresh_token=credentials["refresh_token"],
            token_uri=credentials["token_uri"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            scopes=credentials["scopes"],
    )

    def connect(self):
        """
        Creates an API instance that will be used for fetching
        information from the server.
        """
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())

        self.google_photos = build('photoslibrary', 'v1',
                                   credentials=self.credentials,
                                   static_discovery=False)

    def disconnect(self):
        """
        Terminates the connection.
        """
        assert self.google_photos is not None
        self.google_photos.close()
        self.google_photos = None

    def get_album_dict(self):
        """
        Retrieves all albums associated with the user and their
        metadata.
        """
        to_return = {}
        nextpage = ''

        while nextpage != 'no next page':
            result = self.google_photos.albums().list(pageSize=50, pageToken=nextpage).execute()
            for album in result.get('albums', []):
                to_return[album['title']] = album['id']
            nextpage = result.get('nextPageToken', 'no next page')

        return to_return

    def get_photos_from_album(self, album_id: str):
        """
        Given an album id, retrieves all media items present in
        said album.
        """
        to_return = []
        nextpage = ''
        if album_id == '':
            response = self.google_photos.mediaItems().list(pageSize=50,
                                                            pageToken=nextpage).execute()
            to_return = response.get('mediaItems', [])
        else:
            while nextpage != 'no next page':
                body = { 'albumId': album_id,
                         'pageSize': 50,
                         'pageToken': nextpage
                        }
                result = self.google_photos.mediaItems().search(body=body).execute()
                to_return.extend(result.get('mediaItems', []))
                nextpage = result.get('nextPageToken', 'no next page')

        return to_return

    @classmethod
    def get_item_size(cls, base_url) -> int:
        """
        Fetches the size of an item recognizable by its base url
        from the server.
        """
        size = requests.head(base_url+'=d', allow_redirects=True).headers['Content-Length']
        return int(size)

    @classmethod
    def get_file_content(cls, url: str, maxw: int, maxh: int) -> bytes:
        """
        Fetches the content of a chosen file from the server.
        """
        attach = f'=w{maxw}-h{maxh}'
        content = requests.get(url+attach, allow_redirects=True).content
        return content
