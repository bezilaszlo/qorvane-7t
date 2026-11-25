from app.db import ConnDep, ReadConnDep


# The default "request" scope would run the commit after the response is sent.
def test_connection_dependencies_commit_before_response():
    for dep in (ConnDep, ReadConnDep):
        assert dep.__metadata__[0].scope == "function"
