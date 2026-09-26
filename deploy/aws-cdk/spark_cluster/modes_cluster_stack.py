"""
Spark Modes Cluster Stack - two-node heterogeneous Spark cluster used by
deploy/run_aws_modes.ps1 to measure every inference execution mode (RDD
cpu/gpu/hybrid, GPU-aware scheduling, pandas UDF, Spark's native
predict_batch_udf, and Triton-backed predict_batch_udf) across workers.

  cpu node : m5.2xlarge  - Spark master + driver + CPU worker (4 cores)
  gpu node : g4dn.xlarge - Spark GPU worker (4 cores, GPU resource advertised)
                           + Triton Inference Server
Both on the AWS Deep Learning Base AMI (Docker + BuildKit + NVIDIA container
toolkit preinstalled; the NVIDIA driver simply stays unloaded on the m5),
same public subnet, SSM-managed (no SSH), security group open only to itself
so Spark's driver/executor/block-manager ephemeral ports and Triton's
8000-8002 work between the nodes. Nothing is reachable from the internet.
"""
from aws_cdk import CfnOutput, RemovalPolicy, Stack, Tags
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct


class SparkModesClusterStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        cpu_type = self.node.try_get_context("cpu_instance_type") or "m5.2xlarge"
        gpu_type = self.node.try_get_context("gpu_instance_type") or "g4dn.xlarge"

        vpc = ec2.Vpc(self, "ModesVpc", max_azs=1, nat_gateways=0,
                      subnet_configuration=[ec2.SubnetConfiguration(
                          name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24)])

        sg = ec2.SecurityGroup(self, "ModesSg", vpc=vpc, allow_all_outbound=True,
                               description="Spark modes cluster - intra-cluster only")
        sg.add_ingress_rule(sg, ec2.Port.all_traffic(), "Spark + Triton between cluster nodes")

        bucket = s3.Bucket(self, "ModesBucket", removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True,
                           block_public_access=s3.BlockPublicAccess.BLOCK_ALL)

        role = iam.Role(self, "ModesRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                        managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name(
                            "AmazonSSMManagedInstanceCore")])
        bucket.grant_read_write(role)

        ami = ec2.MachineImage.lookup(name="Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04) *",
                                      owners=["amazon"])

        def node(cid, itype, name):
            ud = ec2.UserData.for_linux()
            ud.add_commands(
                "systemctl enable docker && systemctl start docker",
                "apt-get update -y && apt-get install -y unzip jq || true",
                "nvidia-ctk runtime configure --runtime=docker || true",
                "systemctl restart docker",
                f"echo 'BUCKET={bucket.bucket_name}' >> /etc/environment",
                "mkdir -p /opt/modes",
                "echo 'shutdown -h now' | at now + 4 hours 2>/dev/null || true",  # cost safety net
            )
            inst = ec2.Instance(self, cid, vpc=vpc, instance_type=ec2.InstanceType(itype), machine_image=ami,
                                security_group=sg, role=role, user_data=ud,
                                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                                associate_public_ip_address=True,
                                block_devices=[ec2.BlockDevice(device_name="/dev/sda1",
                                               volume=ec2.BlockDeviceVolume.ebs(200, volume_type=ec2.EbsDeviceVolumeType.GP3))])
            Tags.of(inst).add("Name", name)
            return inst

        cpu = node("CpuNode", cpu_type, "spark-modes-cpu-master")
        gpu = node("GpuNode", gpu_type, "spark-modes-gpu-worker")

        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "CpuInstanceId", value=cpu.instance_id)
        CfnOutput(self, "CpuPrivateIp", value=cpu.instance_private_ip)
        CfnOutput(self, "GpuInstanceId", value=gpu.instance_id)
        CfnOutput(self, "GpuPrivateIp", value=gpu.instance_private_ip)
