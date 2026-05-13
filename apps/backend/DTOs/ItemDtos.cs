namespace TargetBackend.DTOs;

public record CreateItemRequest(string Name, string? Description);
public record UpdateItemRequest(string Name, string? Description, bool IsActive);
public record ItemResponse(Guid Id, string Name, string? Description, bool IsActive, DateTime CreatedAt, DateTime? UpdatedAt);
