FROM harbor.iccl.local:8088/pre6g/yolo26-base:0.1

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Keep the current workload directory mostly intact while allowing more than one
# frequently-changed file into the app layer.
COPY ./*.py /app/
COPY ./startup*.sh /app/
COPY build_and_import_image_to_k3s.sh /app/build_and_import_image_to_k3s.sh

RUN chmod +x /app/startup.app.sh /app/build_and_import_image_to_k3s.sh

EXPOSE 18080

CMD ["/app/startup.app.sh"]
