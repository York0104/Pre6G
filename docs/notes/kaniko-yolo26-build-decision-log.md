# Kaniko YOLO26 Build Decision Log

## 2026-06-14: Split Build Context Strategy

Decision:
For split image builds, use initContainer clone + dir:// context instead of Kaniko git context + context-sub-path.

Reason:
The full build path works with the default Dockerfile name, but split image builds use Dockerfile.base and Dockerfile.app. The combination of Kaniko git context, context-sub-path, and custom Dockerfile names caused Dockerfile path resolution failure before build execution.

Impact:
The initContainer clone approach adds a small YAML overhead but makes the build context explicit. It also makes validation easier because the cloned repo contents can be checked before Kaniko starts the build.
