# OCI Always Free

Target shape: Ampere A1 ARM64, Ubuntu LTS, Docker Compose, no paid load balancer, no managed database assumption.

Before provisioning or deploying, run:

```bash
npm run deploy:preflight
```

The deployment must not create paid resources. Oracle's current Always Free envelope for Ampere A1 is 4 OCPUs and 24 GB memory total across A1 instances, plus 200 GB combined boot and block volume storage in the home region.

This workbench target is exactly `2 OCPU / 12 GB RAM / 50 GB boot` so it can
fit beside another half-sized A1 workload. Before the instance exists, the
preflight fails unless the tenancy has that much remaining Always Free
headroom. After `DEPLOY_TARGET_INSTANCE_NAME` exists, the preflight validates
that target shape, boot volume, and total Always Free usage instead. Use one of
these paths before deploying if capacity is unavailable:

- Resize or repartition the existing A1 instance and co-host the workbench within the 4 OCPU / 24 GB total.
- Free A1 capacity by stopping/deleting or resizing another A1 instance.
- Run local publisher mode and host only static snapshots until A1 capacity is available.

Required gates:

- API image builds for `linux/arm64`
- worker image builds for `linux/arm64`
- fetch sandbox image builds for `linux/arm64`
- migrations run
- minimal ingestion fixture runs

If capacity is unavailable, use local publisher mode to keep public snapshots updated.
