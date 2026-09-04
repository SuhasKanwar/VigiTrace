import sys

class VigiTraceException(Exception):
    def __init__(self, error_message: str, error_detail: sys, status_code: int = 502):
        self.error_message = error_message
        self.status_code = status_code
        _, _, exc_tb = error_detail.exc_info()
        self.line_number = exc_tb.tb_lineno if exc_tb else None
        self.file_name = exc_tb.tb_frame.f_code.co_filename if exc_tb else None

    def __str__(self):
        return "Error occurred in python script name [{0}] line number [{1}] with error message [{2}]".format(self.file_name, self.line_number, self.error_message)
