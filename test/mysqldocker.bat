@echo off
echo 正在启动MySQL8.0 Docker容器...
docker run -d --name root-repo-mysql -p 3306:3306 -e MYSQL_ROOT_PASSWORD=Root123456 -v D:\ROOT\MYSQL_DB:/var/lib/mysql --restart always mysql:8.0
echo 启动完成！
pause