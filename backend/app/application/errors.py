class ConnectivityFailure(Exception):
    def __init__(self, status: int, details):
        super().__init__(str(details))
        self.status, self.details = status, details
