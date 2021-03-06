import multiprocessing
import uuid

from smqtk.utils import SmqtkObject


class IqrController (SmqtkObject):
    """
    Main controlling object for one or more IQR Sessions.

    In order to interface with a web server, methods defined here are
    thread-safe.

    This class may be used with the ``with`` statement. This will enable the
    instance's primary lock, preventing any other action from being performed
    on the instance while inside the with statement. The lock is reentrant, so
    nested with-statements will not dead-lock.

    """

    def __init__(self):
        # Map of uuid to the search state
        #: :type: dict[collections.Hashable, IqrSession]
        self._iqr_sessions = {}

        # RLock for iqr_session{_locks} maps.
        self._map_rlock = multiprocessing.RLock()

    def __enter__(self):
        self._map_rlock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._map_rlock.release()

    def session_uuids(self):
        """
        Return a tuple of all currently registered IqrSessions.

        :return: a tuple of all currently registered IqrSessions.
        :rtype: tuple of collections.Hashable

        """
        with self._map_rlock:
            return tuple(self._iqr_sessions)

    def has_session_uuid(self, session_uuid):
        """ Check if this controller contains a session referenced by the given
        ID.

        Performance using this function is faster compared to getting all UUIDs
        and performing a linear search.

        :param session_uuid: Possible UUID of a session
        :type session_uuid: collections.Hashable

        :return: True of the given UUID references a session in this controller
            and false if not.
        :rtype: bool

        """
        with self._map_rlock:
            return session_uuid in self._iqr_sessions

    def add_session(self, iqr_session, session_uuid=None):
        """ Initialize a new IQR Session, returning the uuid of that session

        :param iqr_session: The IqrSession instance to add
        :type iqr_session: smqtk.iqr.iqr_session.IqrSession

        :param session_uuid: Optional manual specification of the UUID to assign
            to the instance. This cannot already exist in the controller.
        :type session_uuid: collections.Hashable

        :return: UUID of new IQR Session
        :rtype: collections.Hashable

        """
        with self._map_rlock:
            if not session_uuid:
                session_uuid = uuid.uuid1()
                assert session_uuid not in self._iqr_sessions, \
                    "Generated a new random UUID that already exists in " \
                    "session map."
            else:
                if session_uuid in self._iqr_sessions:
                    raise RuntimeError("Cannot use given ID as it already "
                                       "exists in the controller session map: "
                                       "%s" % session_uuid)

            self._iqr_sessions[session_uuid] = iqr_session
            return session_uuid

    def get_session(self, session_uuid):
        """
        Return the session instance for the given UUID

        :raises KeyError: The given UUID doesn't exist in this controller.

        :param session_uuid: UUID if the session to get
        :type session_uuid: collections.Hashable

        :return: IqrSession instance for the given UUID
        :rtype: smqtk.iqr.iqr_session.IqrSession

        """
        with self._map_rlock:
            return self._iqr_sessions[session_uuid]

    def remove_session(self, session_uuid):
        """
        Remove an IQR Session by session UUID.

        :raises KeyError: The given UUID doesn't exist in this controller.

        :param session_uuid: Session UUID
        :type session_uuid: collections.Hashable

        """
        with self._map_rlock:
            with self._iqr_sessions[session_uuid]:
                del self._iqr_sessions[session_uuid]
