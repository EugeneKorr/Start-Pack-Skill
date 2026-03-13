-- Скрипт для поиска зависимостей объекта
-- Использование: p_object_name - название вьюшки или функции
SELECT 
    referencing_entity_name = obj_referencing.relname,
    referencing_type = obj_referencing.relkind,
    referenced_entity_name = obj_referenced.relname
FROM pg_depend 
JOIN pg_rewrite ON pg_depend.objid = pg_rewrite.oid
JOIN pg_class obj_referencing ON pg_rewrite.ev_class = obj_referencing.oid
JOIN pg_class obj_referenced ON pg_depend.refobjid = obj_referenced.oid
WHERE obj_referenced.relname = 'view_master_transactions'; -- Замените на нужный объект
