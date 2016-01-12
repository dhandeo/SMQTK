import cPickle

from smqtk.representation import ClassificationElement
from smqtk.representation.classification_element import NoClassificationError

# Try to import required modules
try:
    import psycopg2
except ImportError:
    psycopg2 = None


__author__ = "paul.tunison@kitware.com"


class PostgresClassificationElement (ClassificationElement):
    """
    PostgreSQL database backed classification element.

    Requires a table of at least 3 fields (column names configurable):

        - type-name :: text
        - uuid :: text
        - classification-binary :: bytea

    """

    # Known psql version compatibility: 9.4
    SELECT_TMPL = ' '.join("""
        SELECT {classification_col:s}
          FROM {table_name:s}
          WHERE {type_col:s} = %(type_val)s
            AND {uuid_col:s} = %(uuid_val)s
        ;
    """.split())

    # Known psql version compatibility: 9.4
    UPSERT_TMPL = ' '.join("""
        WITH upsert AS (
          UPDATE {table_name:s}
            SET {classification_col:s} = %(classification_val)s
            WHERE {type_col:s} = %(type_val)s
              AND {uuid_col:s} = %(uuid_val)s
            RETURNING *
          )
        INSERT INTO {table_name:s}
          ({type_col:s}, {uuid_col:s}, {classification_col:s})
          SELECT %(type_val)s, %(uuid_val)s, %(classification_val)s
            WHERE NOT EXISTS (SELECT * FROM upsert);
    """.split())

    @classmethod
    def is_usable(cls):
        if psycopg2 is None:
            cls.logger().warning("Not usable. Requires psycopg2 module")
            return False
        return True

    def __init__(self, type_name, uuid,
                 table_name='classifications',
                 type_col='type_name', uuid_col='uid',
                 classification_col='classification',
                 db_name='postgres', db_host=None, db_port=None, db_user=None,
                 db_pass=None):
        """
        Initialize new PostgresClassificationElement attached to some database
        credentials.

        We require that storage tables treat uuid AND type string columns as
        primary keys. The type and uuid columns should be of the ``text`` type.
        The binary column should be of the ``bytea`` type.

        Default argument values assume a local PostgreSQL database with a table
        created via the
        ``etc/smqtk/postgres/classification_element/example_table_init.sql``
        file (relative to the SMQTK source tree or install root).

        NOTES:
            - Not all uuid types used here are necessarily of the ``uuid.UUID``
              type, thus the recommendation to use a ``text`` type for the
              column. For certain specific use cases they may be proper
              ``uuid.UUID`` instances or strings, but this cannot be generally
              assumed.

        :param type_name: Name of the type of classifier this classification was
            generated by.
        :type type_name: str

        :param uuid: Unique ID reference of the classification
        :type uuid: collections.Hashable

        :param table_name: String label of the database table to use.
        :type table_name: str

        :param uuid_col: The column label for classification UUID storage
        :type uuid_col: str

        :param type_col: The column label for classification type name storage.
        :type type_col: str

        :param classification_col: The column label for classification binary
            storage.
        :type classification_col: str

        :param db_host: Host address of the Postgres server. If None, we
            assume the server is on the local machine and use the UNIX socket.
            This might be a required field on Windows machines (not tested yet).
        :type db_host: str | None

        :param db_port: Port the Postgres server is exposed on. If None, we
            assume the default port (5423).
        :type db_port: int | None

        :param db_name: The name of the database to connect to.
        :type db_name: str

        :param db_user: Postgres user to connect as. If None, postgres
            defaults to using the current accessing user account name on the
            operating system.
        :type db_user: str | None

        :param db_pass: Password for the user we're connecting as. This may be
            None if no password is to be used.
        :type db_pass: str | None

        """
        super(PostgresClassificationElement, self).__init__(type_name, uuid)

        self.table_name = table_name
        self.type_col = type_col
        self.uuid_col = uuid_col
        self.classification_col = classification_col

        self.db_name = db_name
        self.db_host = db_host
        self.db_port = db_port
        self.db_user = db_user
        self.db_pass = db_pass

    def get_config(self):
        return {
            "table_name": self.table_name,
            "type_col": self.type_col,
            "uuid_col": self.uuid_col,
            "classification_col": self.classification_col,

            "db_name": self.db_name,
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_user": self.db_user,
            "db_pass": self.db_pass,
        }

    def get_psql_connection(self):
        """
        :return: A new connection to the configured database
        :rtype: psycopg2._psycopg.connection
        """
        return psycopg2.connect(
            database=self.db_name,
            user=self.db_user,
            password=self.db_pass,
            host=self.db_host,
            port=self.db_port,
        )

    def has_classifications(self):
        """
        :return: If this element has classification information set.
        :rtype: bool
        """
        try:
            return bool(self.get_classification())
        except NoClassificationError:
            return False

    def get_classification(self):
        """
        Get classification result map, returning a label-to-confidence dict.

        We do no place any guarantees on label value types as they may be
        represented in various forms (integers, strings, etc.).

        Confidence values are in the [0,1] range.

        :raises NoClassificationError: No classification labels/confidences yet
            set.

        :return: Label-to-confidence dictionary.
        :rtype: dict[collections.Hashable, float]

        """
        conn = self.get_psql_connection()
        cur = conn.cursor()
        try:
            # fill in query with appropriate field names, then supply values in
            # execute
            q = self.SELECT_TMPL.format(**{
                "classification_col": self.classification_col,
                "table_name": self.table_name,
                "type_col": self.type_col,
                "uuid_col": self.uuid_col,

            })

            cur.execute(q, {"type_val": self.type_name,
                            "uuid_val": str(self.uuid)})
            r = cur.fetchone()
            # For server cleaning (e.g. pgbouncer)
            conn.commit()

            if not r:
                raise NoClassificationError("No PSQL backed classification for "
                                            "label='%s' uuid='%s'"
                                            % (self.type_name, str(self.uuid)))
            else:
                b = r[0]
                c = cPickle.loads(str(b))
                return c
        except:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def set_classification(self, m=None, **kwds):
        """
        Set the whole classification map for this element. This will strictly
        overwrite the entire label-confidence mapping (vs. updating it)

        Label/confidence values may either be provided via keyword arguments or
        by providing a dictionary mapping labels to confidence values.

        The sum of all confidence values, must be ``1.0`` (e.g. input cannot be
        empty). Due to possible floating point error, we round to the 9-th
        decimal digit.

        NOTE TO IMPLEMENTORS: This abstract method will aggregate, and error
        check, input into a single dictionary and return it. Thus, a ``super``
        call should be made, which will return a dictionary.

        :param m: New labels-to-confidence mapping to set.
        :type m: dict[collections.Hashable, float]

        :raises ValueError: The given label-confidence map was empty or values
            did no sum to ``1.0``.

        """
        m = super(PostgresClassificationElement, self)\
            .set_classification(m, **kwds)

        conn = self.get_psql_connection()
        cur = conn.cursor()
        try:
            upsert_q = self.UPSERT_TMPL.strip().format(**{
                "table_name": self.table_name,
                "classification_col": self.classification_col,
                "type_col": self.type_col,
                "uuid_col": self.uuid_col,
            })
            q_values = {
                "classification_val": psycopg2.Binary(cPickle.dumps(m)),
                "type_val": self.type_name,
                "uuid_val": str(self.uuid),
            }
            # Strip out duplicate white-space
            upsert_q = " ".join(upsert_q.split())

            cur.execute(upsert_q, q_values)
            cur.close()
            conn.commit()
        except:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()