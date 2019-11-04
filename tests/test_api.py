import requests_mock
from inquestlabs import inquestlabs_exception
import pytest
import sys
import os
import requests
sys.path.insert(1, os.path.join(sys.path[0], '..'))


def mocked_400_response_request(*args, **kwargs):
    with requests_mock.Mocker() as mock_request:
        mock_request.get("http://labs_mock.com",
                         json={"error": 400}, status_code=400)
        response = requests.get("http://labs_mock.com")
        return response


def mocked_200_response_unsuccessful_request(*args, **kwargs):
    with requests_mock.Mocker() as mock_request:
        mock_request.get("http://labs_mock.com",
                         json={"success": False}, status_code=200)
        response = requests.get("http://labs_mock.com")
        return response


def test_api_invalid_method(labs):
    with pytest.raises(Exception)as excinfo:
        labs.API("mock", data=None, path=None, method="INVALID", raw=False)

    assert "AssertionError" in str(excinfo.type)


def test_api_invalid_path(labs):
    with pytest.raises(Exception) as excinfo:
        labs.API("mock", data=None, path="invalid", method="GET", raw=False)

    assert "FileNotFound" in str(excinfo.type)


def test_api_exceeded_attempts_to_communicate(labs, mocker):
    mocker.patch('requests.request', side_effect=Exception)
    with pytest.raises(inquestlabs_exception) as excinfo:
        labs.API("mock")

    assert "attempts to communicate with InQuest" in str(excinfo.value)


def test_api_bad_status_code(labs, mocker):
    mocker.patch('requests.request', side_effect=mocked_400_response_request)
    with pytest.raises(inquestlabs_exception) as excinfo:
        labs.API("mock")

    assert "status=400" in str(excinfo.value)


def test_api_unsuccessful_request(labs, mocker):
    mocker.patch('requests.request',
                 side_effect=mocked_200_response_unsuccessful_request)
    with pytest.raises(inquestlabs_exception) as excinfo:
        labs.API("mock")

    assert "status=200 but error communicating" in str(excinfo.value)


def test_api_invalid_method_with_key(labs_with_key):
    with pytest.raises(Exception)as excinfo:
        labs_with_key.API("mock", data=None, path=None,
                          method="INVALID", raw=False)

    assert "AssertionError" in str(excinfo.type)


def test_api_invalid_path_with_key(labs_with_key):
    with pytest.raises(Exception) as excinfo:
        labs_with_key.API("mock", data=None, path="invalid",
                          method="GET", raw=False)

    assert "FileNotFound" in str(excinfo.type)


def test_api_exceeded_attempts_to_communicate(labs_with_key, mocker):
    mocker.patch('requests.request', side_effect=Exception)
    with pytest.raises(inquestlabs_exception) as excinfo:
        labs_with_key.API("mock")

    assert "attempts to communicate with InQuest" in str(excinfo.value)


def test_api_bad_status_code(labs_with_key, mocker):
    mocker.patch('requests.request', side_effect=mocked_400_response_request)
    with pytest.raises(inquestlabs_exception) as excinfo:
        labs_with_key.API("mock")

    assert "status=400" in str(excinfo.value)


def test_api_unsuccessful_request(labs_with_key, mocker):
    mocker.patch('requests.request',
                 side_effect=mocked_200_response_unsuccessful_request)
    with pytest.raises(inquestlabs_exception) as excinfo:
        labs_with_key.API("mock")

    assert "status=200 but error communicating" in str(excinfo.value)