import logging
from xmlrpc import client

logger = logging.getLogger(__name__)


class XMLRPCClient(object):
    """
    Python XML-RPC client to interact with GLPI webservices plugin
    """

    def __init__(self, baseurl, username, password):
        """
        :type baseurl: str
        :type username: str
        :type password: str
        :param baseurl: Base URL of your GLPI instance
        :param username: Webservices API user
        :param password: Webservices API password
        """

        self.serviceurl = baseurl + "/plugins/webservices/xmlrpc.php"
        self.server = client.ServerProxy(
            self.serviceurl, allow_none=True, use_datetime=True
        )
        self.session = None
        self.params = {"username": username, "password": password}

    def __getattr__(self, attr):
        def _get_doc(attr, _help):
            """
            Format docstring for wrapped method
            """

            ret = "Wrapper for GLPI webservices %s method:\n\n" % attr
            ret += "It could be a good idea to see method's reference page:\n"
            ret += (
                "https://forge.glpi-project.org/projects/webservices/wiki/Glpi%s\n\n"
                % attr
            )
            ret += ":param module: webservices module to call (default: glpi)\n"
            ret += ":type module: str\n"
            ret += ":param kwargs: options for %s method:\n\n" % attr

            for (key, value) in _help.items():
                ret += "\t- %s: %s\n" % (key, value)

            ret += "\n:type kwargs: dict"

            return ret

        def call(module="glpi", **kwargs):
            params = {}
            if self.session:
                params["session"] = self.session

            params = {**self.params, **params, **kwargs}

            called_module = getattr(self.server, module)
            return getattr(called_module, attr)(params)

        call.__name__ = attr
        call.__doc__ = _get_doc(attr, call(help=True))
        logger.debug("call")
        return call

    def connect(self, login_name, login_password):
        """
        Connect to a running GLPI instance with webservices plugin enabled.

        :type login_name: str
        :type login_password: str
        :param login_name: GLPI user
        :param login_password: GLPI password
        :rtype dict:
        """

        params = {"login_name": login_name, "login_password": login_password}

        try:
            response = self.doLogin(**params)
            if "session" in response:
                self.session = response["session"]
            return response
        except client.Fault as err:
            logger.error(
                "FaultCode: %s, FaultString: %s", err.faultCode, err.faultString
            )
            return err.faultString
        except client.ProtocolError as err:
            logger.error(
                "URL: %s, headers: %s, Error code: %s, Error message: %s",
                err.url,
                err.headers,
                err.errcode,
                err.errmsg,
            )
            return "Что-то не так с сервером!"
