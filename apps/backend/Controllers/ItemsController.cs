using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TargetBackend.Data;
using TargetBackend.DTOs;
using TargetBackend.Models;

namespace TargetBackend.Controllers;

[ApiController]
[Route("api/[controller]")]
public class ItemsController : ControllerBase
{
    private readonly AppDbContext _db;

    public ItemsController(AppDbContext db) => _db = db;

    [HttpGet]
    public async Task<ActionResult<IEnumerable<ItemResponse>>> GetAll(
        [FromQuery] int page = 1,
        [FromQuery] int pageSize = 20)
    {
        pageSize = Math.Clamp(pageSize, 1, 100);
        var items = await _db.Items
            .OrderByDescending(i => i.CreatedAt)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(i => new ItemResponse(i.Id, i.Name, i.Description, i.IsActive, i.CreatedAt, i.UpdatedAt))
            .ToListAsync();

        return Ok(items);
    }

    [HttpGet("{id:guid}")]
    public async Task<ActionResult<ItemResponse>> GetById(Guid id)
    {
        var item = await _db.Items.FindAsync(id);
        if (item is null) return NotFound();
        return Ok(new ItemResponse(item.Id, item.Name, item.Description, item.IsActive, item.CreatedAt, item.UpdatedAt));
    }

    [HttpPost]
    public async Task<ActionResult<ItemResponse>> Create([FromBody] CreateItemRequest request)
    {
        var item = new Item { Name = request.Name, Description = request.Description };
        _db.Items.Add(item);
        await _db.SaveChangesAsync();

        var response = new ItemResponse(item.Id, item.Name, item.Description, item.IsActive, item.CreatedAt, item.UpdatedAt);
        return CreatedAtAction(nameof(GetById), new { id = item.Id }, response);
    }

    [HttpPut("{id:guid}")]
    public async Task<ActionResult<ItemResponse>> Update(Guid id, [FromBody] UpdateItemRequest request)
    {
        var item = await _db.Items.FindAsync(id);
        if (item is null) return NotFound();

        item.Name = request.Name;
        item.Description = request.Description;
        item.IsActive = request.IsActive;
        item.UpdatedAt = DateTime.UtcNow;
        await _db.SaveChangesAsync();

        return Ok(new ItemResponse(item.Id, item.Name, item.Description, item.IsActive, item.CreatedAt, item.UpdatedAt));
    }

    [HttpDelete("{id:guid}")]
    public async Task<IActionResult> Delete(Guid id)
    {
        var item = await _db.Items.FindAsync(id);
        if (item is null) return NotFound();

        _db.Items.Remove(item);
        await _db.SaveChangesAsync();
        return NoContent();
    }
}
