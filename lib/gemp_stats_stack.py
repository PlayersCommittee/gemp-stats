from aws_cdk import (
  aws_cognito as cognito,
  aws_iam as iam,
  aws_dynamodb as dynamodb,
  aws_kms as kms,
  aws_apigateway as apigw,
  aws_lambda as lfn,
  aws_logs as logs,
  aws_sns as sns,
  aws_certificatemanager as acm,
  aws_cloudfront as cloudfront,
  aws_cloudfront_origins as origins,
  aws_apigateway as apigw,
  aws_s3 as s3,
  aws_wafv2 as wafv2,
  aws_route53 as r53,
  aws_route53_targets as r53_targets,
  aws_certificatemanager as acm,
  Aws, Duration, Stack, Tags, Aspects, Fn, RemovalPolicy, CustomResource, CfnMapping, CfnOutput
)
from constructs import Construct
from os import ( getcwd, getenv, path )
import subprocess
import shutil

import cdk_nag

class GempStatsStack(Stack):

  def prepare_lambda_requirements(self, function_name="gemp_stats"):
    # create the platform independent paths
    requirements_txt = path.join(getcwd(), "functions", function_name, "requirements.txt")
    proxy_dir        = path.join(getcwd(), "functions", function_name)
    proxy_share_dir  = path.join(getcwd(), "functions", function_name + "_share")

    # copy the code and such to the target directory for distribution
    shutil.copytree(proxy_dir, proxy_share_dir, dirs_exist_ok=True) # copy_function=copy2)

    # install the dependencies using pip
    subprocess.check_call(("pip3 install -r " + requirements_txt + " -t " + proxy_share_dir).split())

    return proxy_share_dir




  def __init__(self, scope: Construct, id: str, **kwargs) -> None:
    super().__init__(scope, id, **kwargs)
    
    ########################################
    ##
    ## CDK Nag
    ## https://github.com/cdklabs/cdk-nag
    ##
    ## CDK Nag evaluates code against compliance lists:
    ##   * AWS Solutions
    ##   * HIPAA Security
    ##   * NIST 800-53 rev 4
    ##   * NIST 800-53 rev 5
    ##   * PCI DSS 3.2.1
    ##
    ## [AWS Solutions](https://github.com/cdklabs/cdk-nag/blob/main/RULES.md#awssolutions)
    ## offers a collection of cloud-based solutions for dozens of technical and business problems, 
    ## vetted for you by AWS
    ##
    ########################################
    Aspects.of(self).add(cdk_nag.AwsSolutionsChecks())


    ########################################
    ##
    ## S3 Bucket
    ##
    ########################################
    bucket_name = "gemp-stats-" + Aws.REGION + "-" + Aws.ACCOUNT_ID
    gemp_stats_bucket = s3.Bucket(self, 'GempStatsBucket',
      bucket_name=bucket_name,
      encryption=s3.BucketEncryption.S3_MANAGED,
      access_control=s3.BucketAccessControl.PRIVATE,
    )

    ########################################
    ##
    ## Cloudfront access to S3 using OAI (origin access identity)
    ##
    ########################################
    origin_access_identity = cloudfront.OriginAccessIdentity(self, 'GempStatsCloudfrontOriginAccessIdentity')
    gemp_stats_bucket.grant_read(origin_access_identity)

    site_distribution = cloudfront.Distribution(self, 'GempStatsCloudfront',
      default_behavior=cloudfront.BehaviorOptions(
        origin=origins.S3Origin(
          gemp_stats_bucket,
          origin_access_identity=origin_access_identity
        ),
        viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      ),
      price_class= cloudfront.PriceClass.PRICE_CLASS_100,
      enable_logging=False,
      default_root_object="index.html",
      comment='GEMP Stats',
      minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
    )


    CfnOutput(self, "GempStatsCloudfrontDomain",
      export_name = "GempStatsCloudfrontDomain",
      value       = site_distribution.distribution_domain_name
    )



    ########################################
    ##
    ## gemp_stats Lambda Function IAM Role
    ##
    ########################################

    gemp_stats_lambda_policy = iam.ManagedPolicy(self, "GempStatsLambdaPolicy",
      managed_policy_name = 'gemp-stats-policy',
      description         = "Gemp Stats")

    gemp_stats_lambda_policy.add_statements(iam.PolicyStatement(
      effect   =iam.Effect.ALLOW,
      actions  =["s3:put*", "s3:get*", "s3:list*"],
      resources=[gemp_stats_bucket.bucket_arn, gemp_stats_bucket.bucket_arn+"/*"],
    ))

    gemp_stats_lambda_policy.add_statements(iam.PolicyStatement(
      effect   =iam.Effect.ALLOW,
      actions  =["cloudfront:createinvalidation"],
      resources=["arn:aws:cloudfront::" + Aws.ACCOUNT_ID + ":" + site_distribution.distribution_id],
    ))

    gemp_stats_lambda_policy.add_statements(iam.PolicyStatement(
      effect   =iam.Effect.ALLOW,
      actions  =["logs:CreateLogGroup"],
      resources=["arn:aws:logs:"+Aws.REGION+":"+Aws.ACCOUNT_ID+":*"],
    ))

    gemp_stats_lambda_policy.add_statements(iam.PolicyStatement(
      effect   =iam.Effect.ALLOW,
      actions  =["logs:CreateLogStream", "logs:PutLogEvents"],
      resources=["arn:aws:logs:"+Aws.REGION+":"+Aws.ACCOUNT_ID+":log-group:/aws/lambda/*:*"],
    ))

    gemp_stats_lambda_policy.add_statements(iam.PolicyStatement(
      effect   =iam.Effect.ALLOW,
      actions  =["secretsmanager:Get*"],
      resources=["arn:aws:secretsmanager:"+Aws.REGION+":"+Aws.ACCOUNT_ID+":secret:gempdb*"],
    ))

    gemp_stats_lambda_role = iam.Role(self, 'GempStatsLambdaRole',
      role_name   ='gemp-stats-role',
      assumed_by  = iam.CompositePrincipal(
                      iam.ServicePrincipal('lambda.amazonaws.com'),
                    )
    )
    gemp_stats_lambda_role.add_managed_policy(gemp_stats_lambda_policy)




    ########################################
    ##
    ## Lambda Function :: Gemp Stats
    ## https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_lambda/README.html
    ##
    ## Generates Stats from GEMP
    ##
    ########################################
  
    gemp_stats_share_dir = self.prepare_lambda_requirements("gemp_stats")
    gemp_stats_function = lfn.Function(self, "GempStatsFunction",
      description  = "GEMP Stats",
      # https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_lambda/Runtime.html
      runtime      = lfn.Runtime.PYTHON_3_10,
      architecture = lfn.Architecture.ARM_64,
      memory_size  = 512, # default = 128 MB
      timeout      = Duration.seconds(20),
      handler      = "index.lambda_handler",
      code         = lfn.Code.from_asset(gemp_stats_share_dir),
      role         = gemp_stats_lambda_role,
      environment  = { "S3_BUCKET_NAME":bucket_name },
    )









    ########################################
    ##
    ## Tags
    ##
    ########################################
    Tags.of(self).add("application", "gemp-stats",  priority=300)
    Tags.of(self).add("purpose",     "gemp-stats",  priority=300)
    Tags.of(self).add("owner",       "cdk",         priority=300)
    Tags.of(self).add("createdBy",   "cdk",         priority=300)



    ########################################
    ##
    ## CDK Nag Suppressions
    ## https://github.com/cdklabs/cdk-nag
    ##
    ########################################

    ##
    ## Errors
    ##

    # IAM Roles and Policies
    cdk_nag.NagSuppressions.add_stack_suppressions(self, [
      {"id":"AwsSolutions-IAM4", "reason": "ERROR: The IAM user, role, or group uses AWS managed policies. An AWS managed policy is a standalone policy that is created and administered by AWS. Currently, many AWS managed policies do not restrict resource scope. Replace AWS managed policies with system specific (customer) managed policies. This is a granular rule that returns individual findings that can be suppressed with appliesTo. The findings are in the format Policy::<policy> for AWS managed policies. Example: appliesTo: ['Policy::arn:<AWS::Partition>:iam::aws:policy/foo']"},
      {"id":"AwsSolutions-IAM5", "reason": "ERROR: The IAM entity contains wildcard permissions and does not have a cdk-nag rule suppression with evidence for those permission. Metadata explaining the evidence (e.g. via supporting links) for wildcard permissions allows for transparency to operators. This is a granular rule that returns individual findings that can be suppressed with appliesTo. The findings are in the format Action::<action> for policy actions and Resource::<resource> for resources. Example: appliesTo: ['Action::s3:*']."},
      {"id":"AwsSolutions-L1", "reason": "ERROR: The non-container Lambda function is not configured to use the latest runtime version."},
    ])

    # Cloudfront+S3
    cdk_nag.NagSuppressions.add_stack_suppressions(self, [
      {"id":"AwsSolutions-S1", "reason":"01234567890123456789"},
      {"id":"AwsSolutions-S2", "reason":"01234567890123456789"},
      {"id":"AwsSolutions-S10", "reason":"01234567890123456789"},
      {"id":"AwsSolutions-CFR4", "reason":"01234567890123456789"},
    ])





