#!/usr/bin/env python

"""
InQuest Labs Command Line Driver

Usage:
    inquestlabs [options] dfi list
    inquestlabs [options] dfi details <sha256> [--attributes]
    inquestlabs [options] dfi download <sha256> <path>
    inquestlabs [options] dfi attributes <sha256> [--filter=<filter>]
    inquestlabs [options] dfi search (code|context|metadata|ocr) <keyword>
    inquestlabs [options] dfi search (md5|sha1|sha256|sha512) <hash>
    inquestlabs [options] dfi search (domain|email|filename|ip|url|xmpid) <ioc>
    inquestlabs [options] dfi sources
    inquestlabs [options] dfi upload <path>
    inquestlabs [options] iocdb list
    inquestlabs [options] iocdb search <keyword>
    inquestlabs [options] iocdb sources
    inquestlabs [options] repdb list
    inquestlabs [options] repdb search <keyword>
    inquestlabs [options] repdb sources
    inquestlabs [options] yara (b64re|base64re) <regex> [(--big-endian|--little-endian)]
    inquestlabs [options] yara hexcase <instring>
    inquestlabs [options] yara uint <instring> [--offset=<offset>] [--hex]
    inquestlabs [options] yara widere <regex> [(--big-endian|--little-endian)]
    inquestlabs [options] stats

Options:
    --api=<apikey>      Specify an API key.
    --config=<config>   Configuration file with API key [default: ~/.iqlabskey].
    --debug             Docopt debugging.
    -h --help           Show this screen.
    --hex               Treat <instring> as hex bytes.
    --proxy=<proxy>     Intermediate proxy
    --version           Show version.
"""

# python 2/3 compatability.
from __future__ import print_function

__version__ = 1.0

import configparser
import requests
import hashlib
import random
import docopt
import time
import json
import os

VALID_CAT  = ["ext", "hash", "ioc"]
VALID_EXT  = ["code", "context", "metadata", "ocr"]
VALID_HASH = ["md5", "sha1", "sha256", "sha512"]
VALID_IOC  = ["domain", "email", "filename", "ip", "url", "xmpid"]

########################################################################################################################
class inquestlabs_exception(Exception):
    pass

########################################################################################################################
class inquestlabs_api:
    """
    InQuest Labs API Wrapper
    https://labs.inquest.net
    """

    ####################################################################################################################
    def __init__ (self, api_key=None, config=None, proxies=None, base_url=None, retries=3, verify_ssl=True):
        """
        Instantiate an interface to InQuest Labs. API key is optional but sourced from (in order): argument, environment
        variable, or configuration file. Proxy dictionary is a raw pass thru to python-requests, valid keys are 'http'
        and 'https'.

        :type  api_key:    str
        :param api_key:    API key, optional, can also be supplied via environment variable 'IQLABS_APIKEY'.
        :type  config:     str
        :param config:     Path to configuration file containing API key, default is '~/.iqlabskey'.
        :type  proxies:    dict
        :param proxies:    Optional proxy dictionary to pass down to underlying python-requests library.
        :type  base_url:   str
        :param base_url:   API endpoint.
        :type  retries:    int
        :param retries:    Number of times to attempt API request before giving up.
        :type  verify_ssl: bool
        :param verify_ssl: Toggles SSL certificate verification when communicating with the API.
        """

        self.api_key     = api_key
        self.base_url    = base_url
        self.config_file = config
        self.num_retries = retries
        self.proxies     = proxies
        self.verify_ssl  = verify_ssl

        # if no base URL was specified, use the default.
        if self.base_url is None:
            self.base_url = "https://labs.inquest.net/api"

        # if no config file was supplied, use a default path of ~/.iqlabskey.
        if self.config_file is None:
            self.config_file = os.path.join(os.path.expanduser("~"), ".iqlabskey")

        # if no API key was specified...
        if not self.api_key:

            # check the environment for one
            self.api_key = os.environ.get("IQLABS_APIKEY")

            # if we still don't have an API key, try loading one from the config file. format:
            #   $ cat .iqlabskey
            #   [inquestlabs]
            #   apikey: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
            if not self.api_key and os.path.exists(self.config_file) and os.path.isfile(self.config_file):
                config = configparser.ConfigParser()

                try:
                    config.read(self.config_file)
                except:
                    raise inquestlabs_exception("invalid configuration file: %s" % self.config_file)

                try:
                    self.api_key = config.get("inquestlabs", "apikey")
                except:
                    raise inquestlabs_exception("unable to find inquestlabs.apikey in: %s" % self.config_file)

            # NOTE: if we still don't have an API key that's fine! InQuest Labs will simply work with some rate limits.

    ####################################################################################################################
    def __API (self, api, data=None, path=None, method="GET", raw=False):
        """
        Internal API wrapper.

        :type  api:    str
        :param api:    API endpoint, appended to base URL.
        :type  data:   dict
        :param data:   Optional data dictionary to pass to endpoint.
        :type  path:   str
        :param path:   Optional path to file to pass to endpoint.
        :type  method: str
        :param method: API method, one of "GET" or "POST".
        :type  raw:    bool
        :param raw:    Default behavior is to expect JSON encoded content, raise this flag to expect raw data.

        :rtype:  dict | str
        :return: Response dictionary or string if 'raw' flag is raised.
        """

        assert method in ["GET", "POST"]

        # if a file path was supplied, convert to a dictionary compatible with requests and the labs API.
        files = None

        if path:
            files = dict(file=open(path, "rb"))

        # initialize headers with a custom user-agent and if an API key is available, add an authorization header.
        headers = \
        {
            "User-Agent" : "python-inquestlabs/%s" % __version__
        }

        if self.api_key:
            headers["Authorization"] = "Basic: %s" % self.api_key

        # build the keyword arguments that will be passed to requests library.
        kwargs = \
        {
            "data"    : data,
            "files"   : files,
            "headers" : headers,
            "proxies" : self.proxies,
            "verify"  : self.verify_ssl,
        }

        # make attempts to dance with the API endpoint, use a jittered exponential back-off delay.
        endpoint = self.base_url + api
        attempt  = 0

        while 1:
            try:
                response = requests.request(method, endpoint, **kwargs)
                break

            except:
                # 0.4, 1.6, 6.4, 25.6, ...
                time.sleep(random.uniform(0, 4 ** attempt * 100 / 1000.0))
                attempt += 1

            # retries exhausted.
            if attempt == self.retries:
                message = "exceeded %s attempts to communicate with InQuest Labs API endpoint %s."
                message %= self.retries, endpoint
                raise inquestlabs_exception(message)

        # all good.
        if response.status_code == 200:

            # if the raw flag was raised, return raw content now.
            if raw:
                return response.content

            # otherwise, we convert the assumed JSON response to a python dictionary.
            response_json = response.json()

            # with a 200 status code, success should always be true...
            if response_json['success']:
                return response_json['data']

            # ... but let's handle corner cases where it may not be.
            else:
                message  = "status=200 but error communicating with %s: %s"
                message %= endpoint, response_json.get("error", "n/a")
                raise inquestlabs_exception(message)

        # something went wrong.
        else:
            response_json = response.json()
            message  = "status=%d error communicating with %s: %s"
            message %= response.status_code, endpoint, response_json.get("error", "n/a")
            raise inquestlabs_exception(message)

            # TODO add rate limit tracking and exhaustion check.

    ####################################################################################################################
    def __HASH (self, path=None, bytes=None, algorithm="md5", block_size=16384, fmt="digest"):
        """
        Return the selected algorithms crytographic hash hex digest of the given file.

        :type  path:       str
        :param path:       Path to file to hash or None if supplying bytes.
        :type  bytes:      str
        :param bytes:      str bytes to hash or None if supplying a path to a file.
        :type  algorithm:  str
        :param algorithm:  One of "md5", "sha1", "sha256" or "sha512".
        :type  block_size: int
        :param block_size: Size of blocks to process.
        :type  fmt:        str
        :param fmt:        One of "digest" (str), "raw" (hashlib object), "parts" (array of numeric parts).

        :rtype:  str
        :return: Hash as hex digest.
        """

        def chunks (l, n):
            for i in range(0, len(l), n):
                yield l[i:i+n]

        algorithm = algorithm.lower()

        if   algorithm == "md5":    hashfunc = hashlib.md5()
        elif algorithm == "sha1":   hashfunc = hashlib.sha1()
        elif algorithm == "sha256": hashfunc = hashlib.sha256()
        elif algorithm == "sha512": hashfunc = hashlib.sha512()

        # hash a file.
        if path:
            with open(path, "rb") as fh:
                while 1:
                    data = fh.read(block_size)

                    if not data:
                        break

                    hashfunc.update(data)

        # hash a stream of bytes.
        elif bytes:
            hashfunc.update(bytes)

        # error.
        else:
            raise inquestlabs_exception("hash expects either 'path' or 'bytes'.")

        # return multiplexor.
        if fmt == "raw":
            return hashfunc

        elif fmt == "parts":
            return map(lambda x: int(x, 16), list(chunks(hashfunc.hexdigest(), 8)))

        else: # digest
            return hashfunc.hexdigest()

    ####################################################################################################################
    # hash shorcuts.
    def md5    (self, path=None, bytes=None): return self.__HASH(path=path, bytes=bytes, algorithm="md5")
    def sha1   (self, path=None, bytes=None): return self.__HASH(path=path, bytes=bytes, algorithm="sha1")
    def sha256 (self, path=None, bytes=None): return self.__HASH(path=path, bytes=bytes, algorithm="sha256")
    def sha512 (self, path=None, bytes=None): return self.__HASH(path=path, bytes=bytes, algorithm="sha512")

    ####################################################################################################################
    def dfi_attributes (self, sha256, filter_by=None):
        """
        Retrieve attributes for a given file by SHA256 hash value.

        :type  sha256:  str
        :param sha256:  SHA256 hash for the file we are interested in.
        :type  filter_by: str
        :param filter_by: Optional filter, can be one of 'domain', 'email', 'filename', 'ip', 'url', 'xmpid'.
        :rtype:  dict
        :return: API response.
        """

        # if a filter is specified, sanity check.
        if filter_by:
            filter_by = filter_by.lower()

            if filter_by not in VALID_IOC:
                message  = "invalid attribute filter '%s'. valid filters include: %s"
                message %= filter_by, ", ".join(VALID_IOC)
                raise inquestlabs_exception(message)

        # dance with the API.
        attributes = self.__API("/dfi/details/attributes", dict(sha256=sha256))

        # filter if necessary.
        if filter_by:
            # sample data:
            #     [
            #       {
            #         "category": "ioc",
            #         "attribute": "domain",
            #         "count": 1,
            #         "value": "ancel.To"
            #       },
            #       {
            #         "category": "ioc",
            #         "attribute": "domain",
            #         "count": 1,
            #         "value": "Application.Top"
            #       }
            #     ]
            attributes = [attr for attr in attributes if attr['attribute'] == filter_by]

        # return attributes.
        return attributes

    ####################################################################################################################
    def dfi_details (self, sha256, attributes=False):
        """
        Retrieve details for a given file by SHA256 hash value. Optionally, pull attributes in a second API request
        and append to the data dictionary under the key 'attributes'.

        :type  sha256:     str
        :param sha256:     SHA256 hash for the file we are interested in.
        :type  attributes: bool
        :param attributes: Raise this flag to includes 'attributes' subkey.

        :rtype:  dict
        :return: API response.
        """

        data = self.__API("/dfi/details", dict(sha256=sha256))

        if attributes:
            data['attributes'] = self.dfi_attributes(sha256)

        return data

    ####################################################################################################################
    def dfi_download (self, sha256, path):
        """
        Download requested file and save to path.

        :type  sha256: str
        :param sha256: SHA256 hash for the file we are interested in.
        :type  path:   str
        :param path:   Where we want to save the file.
        """

        # NOTE: we're reading the file directly into memory here! not worried about it as the files are small and we
        # done anticipate any OOM issues.
        data = self.__API("/dfi/download", dict(sha256=sha256), raw=True)

        # ensure we got what we were looking for.
        calculated = self.sha256(bytes=data)

        if calculated != sha256:
            message  = "failed downloading file! expected sha256=%s calculated sha256=%s"
            message %= sha256, calculated
            raise inquestlabs_exception(message)

        # write the file to disk.
        with open(path, "wb+") as fh:
            fh.write(data)

    ####################################################################################################################
    def dfi_list (self):
        """
        Retrieve the most recent DFI entries.

        :rtype:  list
        :return: List of dictionaries.
        """

        return self.__API("/dfi/list")

    ####################################################################################################################
    def dfi_search (self, category, subcategory, keyword):
        """
        Search DFI category/subcategory by keyword. Valid categories include: 'ext', 'hash', and 'ioc'. Valid
        subcategories for each include: ext: 'code', 'context', 'metadata', and 'ocr'. hash: 'md5', 'sha1', 'sha256',
        and 'sha512'. ioc: 'domain', 'email', 'filename', 'ip', 'url', 'xmpid'. See https://labs.inquest.net for more
        information.

        :type  category:    str
        :param category:    Search category, one of 'ext', 'hash', or 'ioc'.
        :type  subcategory: str
        :param subcategory: Search subcategory.
        :type  keyword:     str
        :param keyword:     Keyword, hash, or IOC to search for.

        :rtype:  dict
        :return: API response.
        """

        # normalize to lowercase.
        category    = category.lower()
        subcategory = subcategory.lower()

        # sanity check.
        if category not in VALID_CAT:
            message  = "invalid category '%s'. valid categories include: %s"
            message %= category, ", ".join(VALID_CAT)
            raise inquestlabs_exception(message)

        for c, v in zip(VALID_CAT, [VALID_EXT, VALID_HASH, VALID_IOC]):
            if category == c and subcategory not in v:
                message  = "invalid subcategory '%s' for category '%s'. valid subcategories include: %s"
                message %= subcategory, category, ", ".join(v)
                raise inquestlabs_exception(message)

        # API dance.
        if category == "ext":
            subcategory = "ext_" + subcategory

        if category == "hash":
            data = dict(hash=keyword)
        else:
            data = dict(keyword=keyword)

        return self.__API("/dfi/search/%s/%s" % (category, subcategory), data)

    ####################################################################################################################
    def dfi_sources (self):
        """
        Retrieves the list of YARA hunt rules that run atop of Virus Total Intelligence and fuel the majority of the
        DFI corpus.

        :rtype:  dict
        :return: API response.
        """

        return self.__API("/dfi/sources")

    ####################################################################################################################
    def dfi_upload (self, path):
        """
        Uploads a file to InQuest Labs for Deep File Inspection (DFI). Note that the file must be one of doc, docx, ppt,
        pptx, xls, xlsx.

        :type  path: str
        :param path: Path to file to upload.

        :rtype:  dict
        :return: API response.
        """

        VALID_TYPES = ["doc", "docx", "ppt", "pptx", "xls", "xlsx"]

        # ensure the path exists and points to a file.
        if not os.path.exists(path) or not os.path.isfile(path):
            raise inquestlabs_exception("invalid file path specified for upload: %s" % path)

        # ensure the file is an OLE (pre 2007 Office file) or ZIP (post 2007 Office file).
        with open(path, "rb") as fh:
            if fh.read(2) not in ["\xD0\xCF", "PK"]:
                message  = "unsupported file type for upload, valid files include: %s"
                message %= ", ".join(VALID_TYPES)
                raise inquestlabs_exception(message)

        # dance with the API.
        return self.__API("/dfi/upload", method="POST", path=path)

    ####################################################################################################################
    def stats (self):
        """
        Retrieve statistics from InQuest Labs.

        :rtype:  list
        :return: List of dictionaries.
        """

        return self.__API("/stats")

    ####################################################################################################################
    def yara_b64re (self, regex, endian=None):
        """
        Save time and avoid tedious manual labor by automatically converting plain-text regular expressions into their
        base64 compatible form.

        :type  regex:  str
        :param regex:  Regular expression to convert.
        :type  endian: str
        :param endian: Optional endianess, can be either "BIG" or "LITTLE".

        :rtype:  str
        :return: Base64 matching regular expression.
        """

        # initialize data dictionary with supplied regular expression.
        data = dict(instring=regex)

        # splice in the appropriate endianess option if supplied.
        if endian:
            endian = endian.upper()

            if endian == "BIG":
                data['option'] = "widen_big"
            elif endian == "LITTLE":
                data['option'] = "widen_little"
            else:
                raise inquestlabs_exception("invalid endianess supplied to yara_b64re: %s" % endian)

        # dance with the API and return results.
        return self.__API("/yara/base64re", data)

    ####################################################################################################################
    def yara_hexcase (self, instring):
        """
        Translate hex encoded strings into a regular expression form that is agnostic to MixED CaSE CharACtErS.

        :type  instring: str
        :param instring: String to convert.

        :rtype:  str
        :return: Mixed hex case insensitive regular expression.
        """

        return self.__API("/yara/mixcase", dict(instring=instring))

    ####################################################################################################################
    def yara_widere (self, regex, endian=None):
        """
        Save time and avoid tedious manual labor by automating converting ascii regular expressions widechar forms.

        :type  regex:  str
        :param regex:  Regular expression to convert.
        :type  endian: str
        :param endian: Optional endianess, can be either "BIG" or "LITTLE".

        :rtype:  str
        :return: Widened regular expression.
        """

        # initialize data dictionary with supplied regular expression.
        data = dict(instring=regex)

        # splice in the appropriate endianess option if supplied.
        if endian:
            endian = endian.upper()

            if endian in ["BIG", "LITTLE"]:
                data['kind'] = endian
            else:
                raise inquestlabs_exception("invalid endianess supplied to yara_b64re: %s" % endian)

        # dance with the API and return results.
        return self.__API("/yara/widere", data)

    ####################################################################################################################
    def yara_uint (self, magic, offset=0, is_hex=False):
        """
        Improve the performance of your YARA rules by converting string comparisons into unsigned integer pointer
        dereferences.

        :type  magic:  str
        :param magic:  String we which to convert to unit() trigger.
        :type  offset: int
        :param offset: Optional offset in hex (0xde) or decimal (222) to look for magic at, defaults to 0.
        :type  hex:    bool
        :param hex:    Raise this flag to treat 'magic' as hex encoded bytes.

        :rtype:  str
        :return: YARA condition looking for magic at offset via uint() magic.
        """

        return self.__API("/yara/trigger", dict(trigger=magic, offset=offset, is_hex=is_hex))

########################################################################################################################
########################################################################################################################
########################################################################################################################

def main ():
    args = docopt.docopt(__doc__, version=__version__)

    # --debug is for docopt argument parsing. useful to pipe to: egrep -v "False|None"
    if args['--debug']:
        print(args)
        return

    # instantiate interface to InQuest Labs.
    labs = inquestlabs_api(args['--api'], args['--config'], args['--proxy'])

    ### DFI ############################################################################################################
    if args['dfi']:

        # inquestlabs [options] dfi attributes <sha256> [--filter=<filter>]
        if args['attributes']:
            print(json.dumps(labs.dfi_attributes(args['<sha256>'], args['--filter'])))

        # inquestlabs [options] dfi details <sha256> [--attributes]
        elif args['details']:
            print(json.dumps(labs.dfi_details(args['<sha256>'], args['--attributes'])))

        # inquestlabs [options] dfi download <sha256> <path>
        elif args['download']:
            start = time.time()
            labs.dfi_download(args['<sha256>'], args['<path>'])
            print("saved %s as '%s' in %d seconds." % (args['<sha256>'], args['<path>'], time.time() - start))

        # inquestlabs [options] dfi list
        elif args['list']:
            print(json.dumps(labs.dfi_list()))

        elif args['search']:

            # inquestlabs [options] dfi search (code|context|metadata|ocr) <keyword>
            if args['<keyword>']:
                if args['code']:
                    results = labs.dfi_search("ext", "code", args['<keyword>'])
                elif args['context']:
                    results = labs.dfi_search("ext", "context", args['<keyword>'])
                elif args['metadata']:
                    results = labs.dfi_search("ext", "metadata", args['<keyword>'])
                elif args['ocr']:
                    results = labs.dfi_search("ext", "ocr", args['<keyword>'])
                else:
                    raise inquestlabs_exception("keyword search argument parsing fail.")

            # inquestlabs [options] dfi search (md5|sha1|sha256|sha512) <hash>
            elif args['<hash>']:
                if args['md5']:
                    results = labs.dfi_search("hash", "md5", args['<hash>'])
                elif args['sha1']:
                    results = labs.dfi_search("hash", "sha1", args['<hash>'])
                elif args['sha256']:
                    results = labs.dfi_search("hash", "sha256", args['<hash>'])
                elif args['sha512']:
                    results = labs.dfi_search("hash", "sha512", args['<hash>'])
                else:
                    raise inquestlabs_exception("hash search argument parsing fail.")

            # inquestlabs [options] dfi search (domain|email|filename|ip|url|xmpid) <ioc>
            elif args['<ioc>']:
                if args['domain']:
                    results = labs.dfi_search("ioc", "domain", args['<ioc>'])
                elif args['email']:
                    results = labs.dfi_search("ioc", "email", args['<ioc>'])
                elif args['filename']:
                    results = labs.dfi_search("ioc", "filename", args['<ioc>'])
                elif args['ip']:
                    results = labs.dfi_search("ioc", "ip", args['<ioc>'])
                elif args['url']:
                    results = labs.dfi_search("ioc", "url", args['<ioc>'])
                elif args['xmpid']:
                    results = labs.dfi_search("ioc", "xmpid", args['<ioc>'])
                else:
                    raise inquestlabs_exception("ioc search argument parsing fail.")

            # search results.
            print(json.dumps(results))

        # inquestlabs [options] dfi sources
        elif args['sources']:
            print(json.dumps(labs.dfi_sources()))

        # inquestlabs [options] dfi upload <path>
        elif args['upload']:
            start  = time.time()
            sha256 = labs.dfi_upload(args['<path>'])
            print("successfully uploaded %s in %d seconds." % (args['<path>'], time.time() - start))
            print("see results at: https://labs.inquest.net/dfi/sha256/%s" % sha256)

    ### IOCDB ##########################################################################################################
    elif args['iocdb']:
        pass
        # inquestlabs [options] iocdb list
        # inquestlabs [options] iocdb search <keyword>
        # inquestlabs [options] iocdb sources

    ### REPDB ##########################################################################################################
    elif args['repdb']:
        pass
        # inquestlabs [options] repdb list
        # inquestlabs [options] repdb search <keyword>
        # inquestlabs [options] repdb sources

    ### YARA ###########################################################################################################
    elif args['yara']:

        # normalize big/little endian switches.
        if args['--big-endian']:
            endian = "BIG"
        elif args['--little-endian']:
            endian = "LITTLE"
        else:
            endian = None

        # NOTE: we don't json.dumps() these values as they are likely going to be wanted to be used raw and not piped
        #       into another JSON expectant tool.

        # inquestlabs [options] yara (b64re|base64re) <regex> [(--big-endian|--little-endian)]
        if args['b64re'] or args['base64re']:
            print(labs.yara_b64re(args['<regex>'], endian))

        # inquestlabs [options] yara hexcase <instring>
        elif args['hexcase']:
            print(labs.yara_hexcase(args['<instring>']))

        # inquestlabs [options] yara uint <instring> [--offset=<offset>] [--hex]
        elif args['uint']:
            print(labs.yara_uint(args['<instring>'], args['--offset'], args['--hex']))

        # inquestlabs [options] yara widere <regex> [(--big-endian|--little-endian)]
        elif args['widere']:
            print(labs.yara_widere(args['<regex>'], endian))

    ### MISCELLANEOUS ##################################################################################################
    elif args['stats']:
        print(json.dumps(labs.stats()))


########################################################################################################################
if __name__ == '__main__':
    main()