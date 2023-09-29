from aws_cdk import App

from lib.gemp_stats_stack import GempStatsStack

app = App()
env = {'region': 'us-east-2'}

GempStatsStack(app, "SsoStack", env=env)

app.synth()
